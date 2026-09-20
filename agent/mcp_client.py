# import asyncio
# import sys
# from mcp import ClientSession, StdioServerParameters
# from mcp.client.stdio import stdio_client

# async def main():
#     # server_params = StdioServerParameters(
#     #     command="python",
#     #     args=["mcp_server/server.py"]
#     # )
#     server_params = StdioServerParameters(
#     command=sys.executable,
#     args=["-m", "mcp_server.server"]
#     )

#     async with stdio_client(server_params) as (read,write):
#         async with ClientSession(read,write) as session:

#             await session.initialize()

#             tools = await session.list_tools()

#             print("Discovered tools:")
#             for tool in tools.tools:
#                 print("-", tool.name)
#                 print("  description:", tool.description)
#                 print("  inputSchema:", tool.input_schema)

#             # result = await session.call_tool(
#             #     "search_books",
#             #     arguments={"query": "三体"}
#             # )
#             # result = await session.call_tool(
#             #     "search_books",
#             #     arguments={
#             #         "query": "我想读一本科幻小说",
#             #         "category": "科幻",
#             #         "top_k": 2
#             #     }
#             result = await session.call_tool(
#                 "check_availability",
#                 arguments={"book_id": "B001"}
#             )
            

#             print("\nTool result:")
            
#             for content in result.content:
#                 if content.type == "text":
#                     print(content.text) 

# if __name__ == "__main__":
#     asyncio.run(main())


import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def parse_arguments(items):
    #把 book_id=B001 top_k=3 这种写法解析成 {"book_id": "B001", "top_k": 3}
    arguments = {}

    for item in items:
        if "=" not in item:
            print("参数要写成 key=value 的形式，例如 book_id=B001")
            raise SystemExit(1)

        key, value = item.split("=", 1)

        #纯数字按整数传（top_k=3），其余按字符串传
        arguments[key] = int(value) if value.lstrip("-").isdigit() else value

    return arguments


async def main():
    #不带参数 = 列出所有工具；带参数 = 调用指定工具
    if len(sys.argv) > 1:
        tool_name = sys.argv[1]
        arguments = parse_arguments(sys.argv[2:])
    else:
        tool_name = None
        arguments = {}

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        #MCP 默认只把一部分环境变量传给服务端子进程，这里显式把整个环境传过去，
        #否则 HF_HUB_OFFLINE 传不进去，服务端每次启动都会去 huggingface 检查更新（会卡很久）
        env={**os.environ, "HF_HUB_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            
            await session.initialize()

            tools = await session.list_tools()

            if tool_name is None:
                print("MCP 服务暴露的工具：")
                for tool in tools.tools:
                    print("-", tool.name)
                    print("  说明:", tool.description)
                    print("  参数:", list(tool.input_schema.get("properties", {})))
                return

            result = await session.call_tool(tool_name, arguments=arguments)

            print("调用:", tool_name, arguments)

            for content in result.content:
                if content.type == "text":
                    print(content.text)


if __name__ == "__main__":
    asyncio.run(main())