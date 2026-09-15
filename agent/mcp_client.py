import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    # server_params = StdioServerParameters(
    #     command="python",
    #     args=["mcp_server/server.py"]
    # )
    server_params = StdioServerParameters(
    command="python",
    args=["-m", "mcp_server.server"]
    )

    async with stdio_client(server_params) as (read,write):
        async with ClientSession(read,write) as session:

            await session.initialize()

            tools = await session.list_tools()

            print("Discovered tools:")
            for tool in tools.tools:
                print("-",tool.name)

            # result = await session.call_tool(
            #     "search_books",
            #     arguments={"query": "三体"}
            # )
            result = await session.call_tool(
                "search_books",
                arguments={
                    "query": "我想学习机器学习和神经网络",
                    "top_k": 3
                }
            )

            print("\nTool result:")
            
            for content in result.content:
                if content.type == "text":
                    print(content.text) 

if __name__ == "__main__":
    asyncio.run(main())