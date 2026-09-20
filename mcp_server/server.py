from typing import Annotated

import httpx
from pydantic import Field
from mcp.server import MCPServer

#导入 RAG
from rag.retriever import hybrid_search

mcp = MCPServer("Library MCP Server")


#加 HTTP 调用辅助 
#LMS 后端地址：下面这些业务工具都通过 HTTP 调它，所以用工具前必须先启动后端
LMS_BASE_URL = "http://127.0.0.1:8000"


def _call_lms(method, path, json_body=None):
    """调用 LMS 的 REST 接口，把结果统一成 {"ok": 是否成功, ...}。

    两类失败都在这里一次性处理，工具函数就不用各写一遍：
    1) 连不上后端（后端没启动）→ backend_unreachable
    2) 后端返回 4xx / 5xx → 取出 FastAPI 的 detail.reason 和 detail.message
    """
    try:
        response = httpx.request(
            method,
            LMS_BASE_URL + path,
            json=json_body,
            timeout=10.0
        )
    except httpx.HTTPError as error:
        return {
            "ok": False,
            "status": 0,
            "error": "backend_unreachable",
            "reason": "无法连接图书馆后端服务，请确认后端已启动：" + str(error)
        }

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", {})
        except ValueError:
            detail = {}

        if isinstance(detail, dict):
            return {
                "ok": False,
                "status": response.status_code,
                "error": detail.get("reason", "lms_error"),
                "reason": detail.get("message", response.text)
            }

        return {
            "ok": False,
            "status": response.status_code,
            "error": "lms_error",
            "reason": str(detail)
        }

    return {
        "ok": True,
        "status": response.status_code,
        "data": response.json()
    }




# @mcp.tool()
# def search_books(query: str) -> list[str]:
#     """Search books by title or author."""

#     books = [
#         "三体 - 刘慈欣",
#         "流浪地球 - 刘慈欣",
#         "活着 - 余华",
#         "Python编程: 从入门到实践 - Eric Matthes"
#     ]

#     result = []

#     for book in books:
#         if query.lower() in book.lower():
#             result.append(book)

#     return result

# @mcp.tool()
# def search_books(query: str, top_k: int = 3) -> list[dict]:
#     """Search books using hybrid retrieval."""

#     results = hybrid_search(
#         query,
#         top_k=top_k
#     )

#     books = []

#     for item in results:
#         book = item["book"]

#         books.append({
#             "book_id": book["book_id"],
#             "title": book["title"],
#             "author": book["author"],
#             "category": book["category"],
#             "score": item["score"]
#         })

#     return books


#文档 3.2：search_books(query, category, top_k) -> list[{book_id, title, author, call_number}]
@mcp.tool()
def search_books(query: str,category: str | None = None,top_k: int = 5 ) -> list[dict]:
    """
    按语义 + 关键词混合检索馆藏图书。
    query: 读者想找的书的内容描述，例如"我想学习机器学习和神经网络"
    category: 可选，按类目过滤，例如"计算机"、"科幻"、"文学"、"科普"
    top_k: 最多返回几本书
    """

    #有类目过滤时先多取一些候选，过滤完再截断，避免不够 top_k 条
    if category is None:
        candidate_k = top_k
    else:
        candidate_k = top_k * 3

    results = hybrid_search(
        query,
        top_k=candidate_k
    )

    books = []

    for item in results:
        book = item["book"]

        if category is not None and book["category"] != category:
            continue

        books.append({
            "book_id": book["book_id"],
            "title": book["title"],
            "author": book["author"],
            "call_number": book["call_number"]
        })

        if len(books) >= top_k:
            break

    return books


#check_availability 工具
@mcp.tool()
def check_availability(
    book_id: Annotated[str, Field(description="图书编号，例如 B001")]
) -> dict:
    """查询某本书的可借状态：总册数、在架册数、在架位置、最近应还日期。"""
    result = _call_lms("GET", "/books/" + book_id + "/availability")

    if not result["ok"]:
        #文档 3.2 的失败契约：不抛异常，返回 {"error": ..., "reason": ...}
        return {"error": result["error"], "reason": result["reason"]}

    data = result["data"]

    return {
        "book_id": data["book_id"],
        "title": data["title"],
        "total_copies": data["total_copies"],
        "available_copies": data["available_copies"],
        "on_shelf_locations": data["on_shelf_locations"],
        "next_return_date": data["next_return_date"]
    }


#borrow 工具
@mcp.tool()
def borrow(
    user_id: Annotated[str, Field(description="借书证号，例如 R2025001")],
    book_id: Annotated[str, Field(description="图书编号，例如 B001")]
) -> dict:
    """为读者借出一本图书。成功返回借阅编号和应还日期；失败返回错误代码与原因。"""
    result = _call_lms(
        "POST",
        "/loans",
        {"user_id": user_id, "book_id": book_id}
    )

    if not result["ok"]:
        #文档 3.2 的失败契约：不抛异常，返回 {"error": ..., "reason": ...}
        return {"error": result["error"], "reason": result["reason"]}

    data = result["data"]

    return {
        "loan_id": data["loan_id"],
        "due_at": data["due_at"]
    }



#renew 工具
@mcp.tool()
def renew(
    loan_id: Annotated[str, Field(description="借阅编号，例如 L000001")]
) -> dict:
    """为一条借阅记录续借一次。成功返回新的应还日期；失败返回错误代码与原因。"""
    result = _call_lms("POST", "/loans/" + loan_id + "/renew")

    if not result["ok"]:
        #文档 3.2 的失败契约：不抛异常，返回 {"error": ..., "reason": ...}
        return {"error": result["error"], "reason": result["reason"]}

    data = result["data"]

    return {"new_due_at": data["new_due_at"]}



#return_book 工具
@mcp.tool()
def return_book(
    loan_id: Annotated[str, Field(description="借阅编号，例如 L000001")]
) -> dict:
    """归还一本图书。成功返回归还时间和逾期罚金；
    如果这本书之前已经归还过，会返回 already_returned 为 true 的提示，而不是报错。
    """
    result = _call_lms("POST", "/loans/" + loan_id + "/return")

    if not result["ok"]:
        #文档 3.2 的幂等要求：同一笔借阅归还两次不算失败，第二次给出"已归还"提示
        if result["error"] == "already_returned":
            return {
                "already_returned": True,
                "reason": result["reason"]
            }

        return {"error": result["error"], "reason": result["reason"]}

    data = result["data"]

    return {
        "returned_at": data["returned_at"],
        "fine": data["fine"]
    }


#reserve 工具
@mcp.tool()
def reserve(
    user_id: Annotated[str, Field(description="借书证号，例如 R2025001")],
    book_id: Annotated[str, Field(description="图书编号，例如 B001")]
) -> dict:
    """为读者预约一本暂时借不到的书。成功返回预约编号和当前排队位次；失败返回错误代码与原因。"""
    result = _call_lms(
        "POST",
        "/reservations",
        {"user_id": user_id, "book_id": book_id}
    )

    if not result["ok"]:
        return {"error": result["error"], "reason": result["reason"]}

    data = result["data"]

    return {
        "reservation_id": data["reservation_id"],
        "queue_position": data["queue_position"]
    }



if __name__ == "__main__":
    mcp.run() #无参数默认Stdio，本地构建MCP服务器，本地客户端调用