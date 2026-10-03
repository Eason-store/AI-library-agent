"""skill（技能）：把标准业务流程固化成固定步骤，不让模型每次自己编排。

对应导师的要求："我怎么还书，你可以把书写成一个 skill，就不用他每次都自己去造了。"
（会议录音里出现的"sql"是"skill"的误识）

skill 和 MCP 工具的关系：
  * MCP 工具是原子操作（借出一本、还掉一条、查一本书），一次只做一件事
  * skill 是标准流程（"还书"这件事从头到尾怎么办），内部串联多个原子操作

三条设计原则：
  1. skill 的步骤写死在代码里 —— 每次执行完全一样，不依赖模型临场发挥
  2. skill 的参数尽量是人话（比如书名），内部自己解析成编号（book_id / loan_id）
  3. skill 只负责"执行"，返回的文本仍交给模型组织成人话
     （业务错误的自然语言回复是 Agent 的职责，文档 3.2 的要求）
"""
import json


def result_to_text(result):
    """把 MCP 工具的返回值转成一段文本。

    （和 loop.py 里那份逻辑一样；放在这里是为了让 skill 能独立使用，
      避免 skills 反过来 import loop 造成循环依赖。）
    """
    if isinstance(result.structured_content, dict) and "result" in result.structured_content:
        return json.dumps(result.structured_content["result"], ensure_ascii=False)

    return "\n".join(item.text for item in result.content if item.type == "text")


def match_by_title(loans, book_title):
    """在借阅记录里按书名找，做双向包含匹配，容忍读者只说简称。

    例：读者说"三体"，记录里的书名是"三体"，能匹配；
        读者说"算法"，记录里的书名是"算法设计实践指南"，也能匹配。
    """
    title = (book_title or "").strip()

    if not title:
        return []

    return [
        loan for loan in loans
        if title in loan["book_title"] or loan["book_title"] in title
    ]

async def find_book_id(agent, book_title):
    """用馆藏检索把书名换成 book_id（借书/预约/查状态三个 skill 共用）。

    返回 (book_id, 提示)：
      * 找到唯一一本  → (编号, None)
      * 没找到 / 找到多本 → (None, 给模型看的提示文本)
    """
    title = (book_title or "").strip()

    if not title:
        return None, "读者没有提供书名。"

    result = await agent.mcp.call_tool(
        "search_books",
        {"query": title, "top_k": 5}
    )

    #直接取结构化结果，比"把文本再解析回 JSON"更稳
    structured = result.structured_content
    books = structured.get("result", []) if isinstance(structured, dict) else []

    #书名完全一样的最优先（比如"活着"要挑出《活着》，而不是《活着为了讲述》）
    exact = [book for book in books if book["title"] == title]

    if len(exact) == 1:
        return exact[0]["book_id"], None

    if len(books) == 1:
        return books[0]["book_id"], None

    if not books:
        return None, "馆藏里没有找到《" + title + "》这本书。"

    candidates = "、".join(
        "《" + book["title"] + "》(" + book["book_id"] + ")"
        for book in books[:5]
    )

    return None, "找到多本相近的书：" + candidates + "，请让读者确认要哪一本。"


async def return_book_skill(agent, arguments):
    """还书流程（固定三步）。

    ① 取当前读者的未归还借阅记录（结构化数据，含 loan_id 和书名）
    ② 按书名找到对应的那一条（找不到 / 找到多条都要如实报告）
    ③ 调 MCP 的 return_book 工具，把结果返回给模型
    """
    book_title = arguments.get("book_title", "")

    user, active_loans = await agent.fetch_reader_state()
    matched = match_by_title(active_loans, book_title)

    if not matched:
        return "当前读者名下没有借着《" + book_title + "》这本书，无法归还。请先确认书名。"

    if len(matched) > 1:
        titles = "、".join("《" + loan["book_title"] + "》" for loan in matched)
        return "匹配到多本在借的书：" + titles + "，请让读者确认要还哪一本。"

    loan = matched[0]

    result = await agent.mcp.call_tool("return_book", {"loan_id": loan["loan_id"]})

    return "已按标准流程办理还书（借阅编号 " + loan["loan_id"] + "）：\n" + result_to_text(result)

async def check_book_skill(agent, arguments):
    """查馆藏状态（固定两步）：按书名找 book_id → 查可借状态。"""
    book_title = arguments.get("book_title", "")
    book_id, hint = await find_book_id(agent, book_title)

    if book_id is None:
        return hint

    result = await agent.mcp.call_tool("check_availability", {"book_id": book_id})

    return "《" + book_title + "》(" + book_id + ") 的馆藏状态：\n" + result_to_text(result)


async def renew_book_skill(agent, arguments):
    """续借（固定两步）：在借记录里找 loan_id → 调 renew。"""
    book_title = arguments.get("book_title", "")

    user, active_loans = await agent.fetch_reader_state()
    matched = match_by_title(active_loans, book_title)

    if not matched:
        return "当前读者名下没有借着《" + book_title + "》这本书，无法续借。"

    if len(matched) > 1:
        titles = "、".join("《" + loan["book_title"] + "》" for loan in matched)
        return "匹配到多本在借的书：" + titles + "，请让读者确认要续借哪一本。"

    loan = matched[0]

    result = await agent.mcp.call_tool("renew", {"loan_id": loan["loan_id"]})

    return "已按标准流程办理续借（借阅编号 " + loan["loan_id"] + "）：\n" + result_to_text(result)


async def borrow_book_skill(agent, arguments):
    """借书（固定两步）：按书名找 book_id → 调 borrow。

    注意：没有在架副本、额度已满、有逾期未还这三种情况，这里都不判断，
    统一交给服务端返回结果 —— 业务规则只有一份（规则死在服务端，文档 3.1）。
    """
    book_title = arguments.get("book_title", "")
    book_id, hint = await find_book_id(agent, book_title)

    if book_id is None:
        return hint

    result = await agent.mcp.call_tool(
        "borrow",
        {"user_id": agent.user_id, "book_id": book_id}
    )

    return "已按标准流程办理借书（书号 " + book_id + "）：\n" + result_to_text(result)


async def reserve_book_skill(agent, arguments):
    """预约（固定两步）：按书名找 book_id → 调 reserve。"""
    book_title = arguments.get("book_title", "")
    book_id, hint = await find_book_id(agent, book_title)

    if book_id is None:
        return hint

    result = await agent.mcp.call_tool(
        "reserve",
        {"user_id": agent.user_id, "book_id": book_id}
    )

    return "已按标准流程办理预约（书号 " + book_id + "）：\n" + result_to_text(result)


#给模型看的 skill 清单（格式和 MCP 工具一样，都是 OpenAI 的 function calling 格式）
SKILL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "skill_check_book",
            "description": (
                "【标准流程】查一本书的馆藏状态（总册数、在架册数、在架位置、最近应还日期）。"
                "读者说'有没有《XX》''《XX》在哪个位置'时用这个。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book_title": {"type": "string", "description": "书名，例如 活着"}
                },
                "required": ["book_title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_borrow_book",
            "description": (
                "【标准流程】帮当前读者借一本书：内部会自动查找书号并办理借出。"
                "读者说'我要借《XX》'时用这个；"
                "不要自己先调 search_books 找书号、再调 borrow，那样要多来回几次。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book_title": {"type": "string", "description": "书名，例如 活着"}
                },
                "required": ["book_title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_return_book",
            "description": (
                "【标准流程】帮当前读者归还一本书：内部会自动在读者的在借记录里找到这本书、"
                "取出借阅编号并办理归还。"
                "读者说'我要还《XX》'时用这个；"
                "不要自己先查借阅记录、再调 return_book，那样容易取错编号。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book_title": {"type": "string", "description": "要归还的书名，例如 三体"}
                },
                "required": ["book_title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_renew_book",
            "description": (
                "【标准流程】帮当前读者续借一本书：内部会自动找到对应的借阅编号并办理续借。"
                "读者说'帮我续借《XX》'时用这个。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book_title": {"type": "string", "description": "要续借的书名，例如 三体"}
                },
                "required": ["book_title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_reserve_book",
            "description": (
                "【标准流程】帮当前读者预约一本书：内部会自动查找书号并办理预约排队。"
                "读者说'帮我预约《XX》'时用这个（通常是在书都被借走时）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "book_title": {"type": "string", "description": "要预约的书名，例如 算法导论"}
                },
                "required": ["book_title"]
            }
        }
    }
]

#skill 名字集合，loop.py 用它来判断"这次调用是 skill 还是普通 MCP 工具"
SKILL_NAMES = {tool["function"]["name"] for tool in SKILL_TOOLS}


async def run_skill(agent, name, arguments):
    """按名字执行 skill，返回一段文本（给模型看）。"""
    if name == "skill_check_book":
        return await check_book_skill(agent, arguments)

    if name == "skill_borrow_book":
        return await borrow_book_skill(agent, arguments)

    if name == "skill_return_book":
        return await return_book_skill(agent, arguments)

    if name == "skill_renew_book":
        return await renew_book_skill(agent, arguments)

    if name == "skill_reserve_book":
        return await reserve_book_skill(agent, arguments)

    return "未知的 skill：" + name