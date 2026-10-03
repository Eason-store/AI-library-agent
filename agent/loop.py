"""LibraryAgent：能对话、能查馆藏、还带读者状态和安全规则的图书馆助手。

到这一步为止它具备：
  1. 多轮上下文（保留最近 8 轮，文档 3.4）
  2. 通过 MCP 调用 6 个工具（文档 3.2）
  3. 规则化预检索，把馆藏检索结果作为上下文（文档 3.3）
  4. Status Bar + Prompt Injection 防御（文档 3.4）

运行方式（必须在项目根目录，而且要先把 LMS 后端启动起来）：
    终端1（后端）：.venv\\Scripts\\python.exe -m uvicorn lms.main:app --port 8000
    终端2（助手）：.venv\\Scripts\\python.exe -m agent.loop 三体还有几册
                   .venv\\Scripts\\python.exe -m agent.loop      （连续对话）
"""
import asyncio
import json
import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AsyncOpenAI

from agent import session as chat_session
from agent import skills
from agent.prompt import build_system_prompt, format_status_bar
from agent.trace import ToolTrace

MODEL = "deepseek-chat"
BASE_URL = "https://api.deepseek.com"

#LMS 后端地址（Status Bar 要从这里读当前读者的状态）
LMS_BASE_URL = "http://127.0.0.1:8000"

#当前登录的读者。演示阶段先写死，真实系统里这个值来自登录态
READER_ID = "R2025001"

#文档 3.4：多轮上下文保留最近 8 轮
MAX_TURNS = 8

#一次提问最多允许连续调用几轮工具（防止模型来回调停不下来）
MAX_TOOL_ROUNDS = 5

#规则化触发（文档八：本档只在"用户明确说查书"时才检索）
#命中这些词才做预检索，避免每句话都去检索一遍
RETRIEVAL_KEYWORDS = [
    "书", "册", "馆藏", "借", "还", "续借", "预约",
    "推荐", "有没有", "找", "查", "作者", "索书号",
    "讲", "相关", "介绍", "经典", "教材", "入门", "进阶"
]


def create_client():
    #从 .env 读密钥，避免把 key 写进代码
    load_dotenv()

    return AsyncOpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=BASE_URL
    )


def should_retrieve(question):
    #只要命中任意一个关键词，就认为"用户明确在问书"
    return any(word in question for word in RETRIEVAL_KEYWORDS)


def mcp_tools_to_openai(tools):
    """把 MCP 的工具描述转成大模型要的 function calling 格式。

    MCP 给的：   {"name": ..., "description": ..., "input_schema": {...}}
    大模型要的： {"type": "function", "function": {"name":..., "description":..., "parameters": {...}}}
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema
            }
        }
        for tool in tools
    ]


def tool_result_to_text(result):
    """把 MCP 工具的返回值转成一段文本，塞回消息里给大模型看。"""
    #返回列表的工具（比如 search_books）MCP 会给结构化结果，优先用它；
    #返回字典的工具结构化结果是空的，这时退回读文本内容
    if isinstance(result.structured_content, dict) and "result" in result.structured_content:
        return json.dumps(result.structured_content["result"], ensure_ascii=False)

    return "\n".join(item.text for item in result.content if item.type == "text")


class LibraryAgent:
    """图书馆助手：带多轮上下文、能调工具、认识当前读者。"""

    def __init__(self, session, user_id=READER_ID, client=None, trace=None, session_id=None):
        #MCP 会话（和 MCP 服务通信）。名字叫 self.mcp，
        #因为现在"会话"有两个意思：MCP 会话 vs 对话会话（chat_session），必须区分开
        self.mcp = session

        self.user_id = user_id                                       #当前登录读者
        self.client = client if client is not None else create_client()
        self.tools = []

        #工具调用轨迹。评测时可以传一个 verbose=False 的进来，避免刷屏
        self.trace = trace if trace is not None else ToolTrace(user_id)

        #对话会话：不指定就新建一个；指定了就恢复它（create_session 是幂等的）
        self.session_id = chat_session.create_session(user_id, session_id)

        #恢复历史：新会话读回空列表，已有会话读回之前的消息
        self.history = chat_session.load_messages(self.session_id)

    async def prepare(self):
        """连上 MCP 之后，把工具清单取回来并转成大模型认识的格式。"""
        tool_list = await self.mcp.list_tools()
        #MCP 的原子工具 + agent 层的 skill（skill 内部会串联多个原子工具）
        self.tools = mcp_tools_to_openai(tool_list.tools) + skills.SKILL_TOOLS

        return [tool["function"]["name"] for tool in self.tools]

    async def fetch_reader_state(self):
        """取当前读者的信息和未归还的借阅记录。

        Status Bar 和 skill 都用这份数据：
          Status Bar 把它拼成给人看的文本，skill 需要结构化的记录来做精确匹配。
        """
        async with httpx.AsyncClient(timeout=10.0) as http:
            user = (await http.get(LMS_BASE_URL + "/users/" + self.user_id)).json()
            loans = (await http.get(LMS_BASE_URL + "/users/" + self.user_id + "/loans")).json()

        active_loans = [loan for loan in loans if loan["returned_at"] is None]

        return user, active_loans

    async def fetch_status_bar(self):
        """取当前读者的最新身份和借阅状态，拼成 Status Bar（文档 3.4）。..."""
        user, active_loans = await self.fetch_reader_state()

        #读者不存在时后端返回的是 {"detail": {...}}，这里兜一下，避免程序直接崩
        if "user_id" not in user:
            return "[当前读者] " + self.user_id + " 未找到（请检查借书证号）"

        return format_status_bar(user, active_loans, datetime.now())

    def _trim(self):
        """只保留最近 MAX_TURNS 轮。

        历史里可能含有 assistant(带 tool_calls) 和 tool 消息，
        所以裁剪时还要保证留下来的历史从"读者提问"开始——
        否则会出现"没有对应 tool_calls 的工具结果"，那是 API 不允许的。
        """
        limit = MAX_TURNS * 2

        if len(self.history) <= limit:
            return

        history = self.history[-limit:]

        #丢掉开头所有不是 user 的消息，直到第一条是读者的提问
        while history and history[0]["role"] != "user":
            history = history[1:]

        self.history = history

    async def build_context(self, question):
        """规则化预检索：命中规则时先检索馆藏，把结果作为本轮上下文。"""
        if not should_retrieve(question):
            return None

        result = await self.mcp.call_tool(
            "search_books",
            {"query": question, "top_k": 5}
        )

        return tool_result_to_text(result)

    async def chat(self, question):
        """问一句话，返回回答。中间如果模型要求调用工具，就在这里执行并继续问。"""
        #文档 3.4：用户输入包在固定分隔符里，防止它被当成系统指令
        self.history.append({
            "role": "user",
            "content": "<user_input>" + question + "</user_input>"
        })

        #存进会话库：存读者原话（不带分隔符），前端展示和恢复会话时都用它
        chat_session.save_message(self.session_id, "user", question)

        self._trim()


        #Status Bar：每次调用模型前重新取一次当前读者的状态
        status_bar = await self.fetch_status_bar()
        system_prompt = build_system_prompt(status_bar)

        #规则化预检索：这次提问如果命中"查书"规则，就先检索馆藏
        context = await self.build_context(question)

        extra = []

        if context:
            #终端打印统一受 trace 的 verbose 控制（评测时关掉，避免刷屏）
            if self.trace.verbose:
                print("  [预检索] " + context[:120].replace("\n", " "))
            #检索结果只对"本轮"有效，所以放在 extra 里，不写进 self.history
            extra.append({
                "role": "system",
                "content": "【馆藏检索结果】以下是系统检索到的馆藏信息，回答时请优先参考：\n" + context
            })

        for _ in range(MAX_TOOL_ROUNDS):
            messages = [{"role": "system", "content": system_prompt}] + extra + self.history

            response = await self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=self.tools,
                #temperature=0：让输出尽量稳定，评测才能复现
                #（默认温度是 1.0，同一个问题两次可能答得不一样，评测就会偶发失败）
                temperature=0
            )

            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            #模型没有要求调工具：这就是最终回答，收工
            if finish_reason != "tool_calls":
                answer = message.content
                self.history.append({"role": "assistant", "content": answer})
                chat_session.save_message(self.session_id, "assistant", answer)
                return answer
            

            #模型要求调工具：先把它的要求记进历史（tool 消息必须对应 tool_calls，这步不能省）
            self.history.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [call.model_dump() for call in message.tool_calls]
            })

            #先判断是 skill 还是普通工具
            for call in message.tool_calls:
                name = call.function.name
                arguments = json.loads(call.function.arguments)

                if name in skills.SKILL_NAMES:
                    #skill：走固定的多步流程（内部自己去调 MCP 工具）
                    text = await skills.run_skill(self, name, arguments)
                else:
                    #普通 MCP 工具：直接调
                    result = await self.mcp.call_tool(name, arguments=arguments)
                    text = tool_result_to_text(result)

                #记一笔轨迹（终端打印也由它负责）
                self.trace.record(name, arguments, text)



                self.history.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": text
                })

        answer = "（工具调用次数过多，我先停下了，请换个问法）"
        chat_session.save_message(self.session_id, "assistant", answer)
        return answer


async def main():
    
    #命令行参数：--session <会话编号> 用来恢复某个会话继续聊
    argv = sys.argv[1:]
    session_id = None

    if len(argv) >= 2 and argv[0] == "--session":
        session_id = argv[1]
        argv = argv[2:]

    #--list：只列出最近的会话就退出（不启动 MCP，也不用等模型加载，几秒出结果）
    if argv and argv[0] == "--list":
        for row in chat_session.list_sessions()[:10]:
            print(row["session_id"] + "  " + str(row["message_count"]) + " 条  " + row["title"])
    
        return

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        #显式把整个环境传给子进程，否则 HF_HUB_OFFLINE 传不进去，MCP 服务会去联网检查模型
        env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            agent = LibraryAgent(session, session_id=session_id)
            names = await agent.prepare()
            status_bar = await agent.fetch_status_bar()

            print("已连接 MCP 服务，可用工具：" + "、".join(names))
            print(status_bar)
            print("会话编号：" + agent.session_id + "（历史消息 " + str(len(agent.history)) + " 条）")

            #带参数：问一句就退出
            if argv:
                question = " ".join(argv)
                print("读者：" + question)
                print("助手：" + str(await agent.chat(question)))
                print("工具调用轨迹已保存：" + agent.trace.save("once"))
                #把"继续这个会话"的完整命令打出来，省得手抄会话编号（容易抄错）
                print("要继续这个会话，用：python -m agent.loop --session " + agent.session_id)
                return

            #交互模式：顺便列出最近的会话，方便下次用 --session 恢复
            print("最近的会话：")

            for row in chat_session.list_sessions()[:5]:
                print("  " + row["session_id"] + "  " + row["title"] + "  （" + str(row["message_count"]) + " 条消息）")

            #不带参数：连续对话
            print("（输入 exit 或直接回车退出）")

            while True:
                try:
                    question = input("读者：")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if question.strip() in ("", "exit", "quit"):
                    break

                print("助手：" + str(await agent.chat(question)))
            print("工具调用轨迹已保存：" + agent.trace.save("session"))


if __name__ == "__main__":
    asyncio.run(main())