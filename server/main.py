from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-auth-demo", stateless_http=True, json_response=True)


@mcp.tool()
def get_time() -> str:
    """Return the current UTC time."""
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
