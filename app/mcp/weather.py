"""Weather MCP server and tool"""

from mcp.server.fastmcp import FastMCP
from opentelemetry import trace
from custom_span import otel_span_decorator

mcp = FastMCP(host="0.0.0.0", stateless_http=True)  # nosec B104 - required for container runtime


@mcp.tool()
@otel_span_decorator(span_name="get_weather")
def get_weather() -> str:
    """Get current wether"""
    # Set span attributes for observability
    span = trace.get_current_span()
    span.set_attribute("gateway.response.body", "Sunny")
    return "Sunny"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
