"""Strands Culinary Assistant"""

# pylint: disable=W0718

import os

from ddgs import DDGS
from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from strands.telemetry import StrandsTelemetry

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token

from opentelemetry.trace import get_tracer_provider
from opentelemetry.propagate import inject
from opentelemetry.processor.baggage import BaggageSpanProcessor, ALLOW_ALL_BAGGAGE_KEYS

from mcp.client.streamable_http import streamablehttp_client


MODEL_ID = os.getenv("BEDROCK_MODEL_ID")
REGION = os.getenv("AWS_REGION", "us-east-1")
SYSTEM_PROMPT = """
You are the Culinary Assistant, a sophisticated restaurant recommendation assistant.
PURPOSE:
- Help users discover restaurants
- Provide upto 3 dining recommendations
- Include street address for the restaurant recommendation

CRITICAL: Every recommended restaurant MUST have a full street address. Never recommend a restaurant without one. If initial search results lack addresses, perform additional searches until you find them. Do not recommend closed restaurants.

You have access to a web search tool that enables you to:
- Look for restaurants in a area
- Retrieve street address for the recommended restaurant

You also have access to tools to retrieve and update order status.

When a user requests multiple things (e.g., recommendations and order status), call all relevant tools in parallel.
"""

# This processor copies all baggage items to span attributes
get_tracer_provider().add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))

# Initialize Strands telemetry for 3P
if os.getenv("DISABLE_ADOT_OBSERVABILITY"):
    strands_telemetry = StrandsTelemetry()
    strands_telemetry.setup_otlp_exporter()

# Initialize agent application wrapper
app = BedrockAgentCoreApp()


@requires_access_token(
    provider_name=os.getenv("ACI_GW_OAUTH2_PROVIDER_NAME"),
    scopes=os.getenv("ACI_GW_OAUTH2_SCOPES").split(","),
    auth_flow='M2M',
)
async def get_token_2lo_async(*, access_token: str) -> str:
    """Retrieves access token using ACI"""
    return access_token


@tool
def web_search(query: str) -> str:
    """
    Search the web for information using DuckDuckGo.
    Args:
        query: The search query
    Returns:
        A string containing the search results
    """
    try:
        ddgs = DDGS()
        results = ddgs.text(query, max_results=3)
        formatted_results = []
        for i, result in enumerate(results, 1):
            formatted_results.append(
                f"{i}. {result.get('title', 'No title')}\n"
                f"   {result.get('body', 'No summary')}\n"
                f"   Source: {result.get('href', 'No URL')}\n"
            )
        return "\n".join(formatted_results) if formatted_results else "No results found."
    except Exception as e:
        return f"Error searching the web: {str(e)}"


@app.entrypoint
async def strands_agent_bedrock(payload):
    """
    Invoke the agent with a payload
    """
    user_input = payload.get("prompt")
    print("User input:", user_input)
    model = BedrockModel(
        model_id=MODEL_ID,
    )
    access_token = await get_token_2lo_async(access_token="")  # nosec B106 - placeholder, replaced by decorator
    # Propagate OTel trace context to the MCP Gateway
    headers = {"Authorization": f"Bearer {access_token}"}
    inject(headers)
    mcp_client = MCPClient(
        lambda: streamablehttp_client(
            url=os.getenv("AGENTCORE_GW_URL"),
            headers=headers,
        )
    )
    with mcp_client:
        agent = Agent(
            tools=[web_search] + mcp_client.list_tools_sync(),
            model=model,
            system_prompt=SYSTEM_PROMPT
        )
        try:
            # Stream each chunk as it becomes available
            async for event in agent.stream_async(user_input):
                if "data" in event:
                    yield event["data"]
        except Exception as e:
            # Handle errors gracefully in streaming context
            error_response = {"error": str(e), "type": "stream_error"}
            print(f"Streaming error: {error_response}")
            yield error_response


if __name__ == "__main__":
    app.run()
