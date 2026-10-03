"""评测脚本：检索评测 + 端到端评测，对应文档六-3 的三项指标。

1. 检索评测（type=retrieval）：BM25 / 向量 / 融合三种召回各自的 Recall@5
2. 端到端评测（type=e2e）：跑真实的 Agent，算任务成功率、工具调用正确率、注入拒绝率

运行方式（必须在项目根目录，而且要先把 LMS 后端启动起来）：
    终端1（后端）：.venv\\Scripts\\python.exe -m uvicorn lms.main:app --port 8000
    终端2（评测）：.venv\\Scripts\\python.exe -m eval.run_eval

脚本会自动保证数据可复现：跑之前重新灌一次数据，跑完之后再灌一次恢复原状。
"""
#在 import rag 之前设好离线标志，避免去 HuggingFace 检查模型更新（那会卡几分钟）
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import lms.seed
from agent.loop import LibraryAgent, LMS_BASE_URL
from agent.trace import ToolTrace
from rag.retriever import bm25_search, hybrid_search, vector_search


# ===== 用例读取 =====

def load_cases(case_type=None):
    """读 eval/cases.jsonl。case_type 为 None 读全部，否则只读指定的 type。"""
    cases = []

    with open("eval/cases.jsonl", "r", encoding="utf-8") as file:
        for line in file:
            #如果遇到空白行，直接跳过去，不要拿空白行执行 json.loads()
            line = line.strip()
            if not line:
                continue

            case = json.loads(line)

            if case_type is not None and case.get("type", "retrieval") != case_type:
                continue

            cases.append(case)

    return cases


# ===== 一、检索评测 =====

# 找到的相关书数量 ÷ 所有应该找到的相关书数量
def recall_at_k(results, relevant_ids):
    retrieved_ids = [
        item["book"]["book_id"]
        for item in results
    ]

    relevant_set = set(relevant_ids)
    retrieved_set = set(retrieved_ids)

    hits = len(relevant_set & retrieved_set)

    return hits / len(relevant_set)


def evaluate(search_function, cases, top_k=5):
    """对每个 query 跑一次检索，再算 Recall，最后取平均值。"""
    recalls = []

    for case in cases:
        query = case["query"]
        relevant_ids = case["relevant_ids"]

        results = search_function(query, top_k=top_k)
        recall = recall_at_k(results, relevant_ids)

        recalls.append(recall)

    average_recall = sum(recalls) / len(recalls)

    return average_recall


def run_retrieval_eval(top_k=5):
    """三种检索方式的 Recall@5 对比（文档 3.3 的教学重点）。"""
    print("===== 检索评测（Recall@" + str(top_k) + "）=====")

    cases = load_cases("retrieval")

    bm25_recall = evaluate(bm25_search, cases, top_k=top_k)
    vector_recall = evaluate(vector_search, cases, top_k=top_k)
    hybrid_recall = evaluate(hybrid_search, cases, top_k=top_k)

    print("BM25   Recall@" + str(top_k) + ": " + f"{bm25_recall:.2f}")
    print("Vector Recall@" + str(top_k) + ": " + f"{vector_recall:.2f}")
    print("Hybrid Recall@" + str(top_k) + ": " + f"{hybrid_recall:.2f}")

    return hybrid_recall


# ===== 二、端到端评测 =====

def judge_tools(calls, case):
    """判断工具调用对不对，返回 (是否通过, 说明)。

    规则：
      1. 调了 forbid_tools 里的工具 → 直接失败（比如"非本人操作"却去调了还书）
      2. expect_tool_any 为空 → 这条不校验工具，通过
      3. 轨迹里存在一条调用：工具名在 expect_tool_any 里，且参数包含 expect_args 全部键值 → 通过
    """
    for call in calls:
        if call["tool"] in case.get("forbid_tools", []):
            return False, "调用了不该调用的工具：" + call["tool"]

    expect_tools = case.get("expect_tool_any", [])

    if not expect_tools:
        return True, "这条用例不校验工具"

    want_args = case.get("expect_args", {})

    for call in calls:
        if call["tool"] not in expect_tools:
            continue

        arguments = call["arguments"]

        if all(arguments.get(key) == value for key, value in want_args.items()):
            return True, call["tool"] + " " + json.dumps(arguments, ensure_ascii=False)

    return False, (
        "没找到期望的工具调用（期望 "
        + str(expect_tools)
        + "，参数 "
        + json.dumps(want_args, ensure_ascii=False)
        + "）"
    )


def judge_answer(answer, case):
    """判断回答文本，返回 (是否通过, 说明)。"""
    for word in case.get("forbid_answer_any", []):
        if word in answer:
            return False, "回答里出现了不该出现的内容：" + word

    expect_words = case.get("expect_answer_any", [])

    if not expect_words:
        return True, "这条用例不校验关键词"

    for word in expect_words:
        if word in answer:
            return True, "命中关键词：" + word

    return False, "回答里没有出现期望关键词：" + " / ".join(expect_words)


async def run_e2e_cases(cases):
    """跑端到端用例。每条用例单独建一个 Agent，互相不干扰。"""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
    )

    results = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("已连接 MCP 服务，工具 " + str(len(tools.tools)) + " 个："
                  + "、".join(tool.name for tool in tools.tools))
            print()

            for case in cases:
                #每条用例：一个干净的 Agent（历史为空）+ 一份轨迹（不打印，避免刷屏）
                trace = ToolTrace(case["reader_id"], verbose=False)
                agent = LibraryAgent(session, user_id=case["reader_id"], trace=trace)
                await agent.prepare()

                answer = await agent.chat(case["query"])

                tool_ok, tool_note = judge_tools(trace.calls, case)
                answer_ok, answer_note = judge_answer(answer, case)

                result = {
                    "id": case["id"],
                    "category": case["category"],
                    "query": case["query"],
                    "answer": answer,
                    "tool_required": bool(case.get("expect_tool_any")),
                    "tool_ok": tool_ok,
                    "answer_ok": answer_ok,
                    "success": tool_ok and answer_ok,
                    "tool_note": tool_note,
                    "answer_note": answer_note,
                    "calls": [call["tool"] for call in trace.calls]
                }

                results.append(result)

                print(("PASS " if result["success"] else "FAIL ") + case["id"]
                      + " [" + case["category"] + "] " + case["query"])
                print("     调用的工具：" + ("、".join(result["calls"]) or "（无）"))

                if not tool_ok:
                    print("     工具判定：" + tool_note)
                if not answer_ok:
                    print("     回答判定：" + answer_note)
                #失败时把回答原文打出来，方便定位原因（成功时不打，避免刷屏）
                if not result["success"]:
                    print("     回答原文：" + answer[:200].replace("\n", " "))

                #轨迹存盘，方便事后回看（verbose=False，所以终端安静）
                trace.save(case["id"])

    return results


def summarize_e2e(results):
    """汇总端到端指标，返回 (任务成功率, 工具调用正确率)。"""
    print()
    print("===== 端到端评测汇总 =====")

    for category in ["normal", "error", "injection"]:
        items = [r for r in results if r["category"] == category]

        if not items:
            continue

        passed = sum(1 for r in items if r["success"])
        print(category + "（" + str(len(items)) + " 条）：成功 " + str(passed) + "/" + str(len(items)))

    #任务成功率：所有用例
    task_passed = sum(1 for r in results if r["success"])
    task_rate = task_passed / len(results)

    #工具调用正确率：只统计"要求工具"的用例（不要求工具的用例无从判断"对不对"）
    tool_items = [r for r in results if r["tool_required"]]
    tool_passed = sum(1 for r in tool_items if r["tool_ok"])
    tool_rate = tool_passed / len(tool_items) if tool_items else 0.0

    #注入拒绝率：文档验收要求 100% 被拒
    injection = [r for r in results if r["category"] == "injection"]
    injection_rate = sum(1 for r in injection if r["success"]) / len(injection) if injection else 0.0

    print()
    print("任务成功率:     " + f"{task_rate:.2f}" + "   (" + str(task_passed) + "/" + str(len(results)) + ")")
    print("工具调用正确率: " + f"{tool_rate:.2f}" + "   (" + str(tool_passed) + "/" + str(len(tool_items)) + "，只统计要求工具的用例)")
    print("注入拒绝率:     " + f"{injection_rate:.2f}" + "   (" + str(sum(1 for r in injection if r["success"])) + "/" + str(len(injection)) + ")")

    return task_rate, tool_rate


# ===== 三、总入口 =====

async def main():
    #端到端评测要调 5 个业务工具，它们都依赖 LMS 后端，所以先做个连通性检查
    try:
        httpx.get(LMS_BASE_URL + "/health", timeout=5)
    except httpx.HTTPError:
        print("连不上 LMS 后端，请先在另一个终端启动它：")
        print("    .venv\\Scripts\\python.exe -m uvicorn lms.main:app --port 8000")
        return

    print("先重新灌一次数据，保证评测从标准状态开始")
    lms.seed.main()
    print()

    run_retrieval_eval()

    print()
    print("===== 端到端评测（20 条用例，会调用大模型，需要几分钟）=====")

    e2e_cases = load_cases("e2e")
    results = await run_e2e_cases(e2e_cases)
    summarize_e2e(results)

    print()
    print("评测结束，重新灌数据恢复到标准状态")
    lms.seed.main()


if __name__ == "__main__":
    asyncio.run(main())