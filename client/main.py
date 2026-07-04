# TODO: this is a throwaway script for Phase 1's plumbing check. Once we
# settle the CLI shape (one-shot vs. login+call), rewrite this as a proper
# CLI tool (click) that handles auth, not just a hardcoded tool call.
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://127.0.0.1:8000/mcp"


async def main():
    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_time", {})
            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(main())
