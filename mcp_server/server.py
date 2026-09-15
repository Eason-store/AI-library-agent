from mcp.server import MCPServer
#导入 RAG
from rag.retriever import hybrid_search

mcp = MCPServer("Library MCP Server")

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

@mcp.tool()
def search_books(query: str, top_k: int = 3) -> list[dict]:
    """Search books using hybrid retrieval."""

    results = hybrid_search(
        query,
        top_k=top_k
    )

    books = []

    for item in results:
        book = item["book"]

        books.append({
            "book_id": book["book_id"],
            "title": book["title"],
            "author": book["author"],
            "category": book["category"],
            "score": item["score"]
        })

    return books


if __name__ == "__main__":
    mcp.run() #无参数默认Stdio，本地构建MCP服务器，本地客户端调用