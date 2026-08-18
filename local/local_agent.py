"""Demo AgentCore Gateway OAuth"""
# pylint: disable=W1203

import os
import logging
import asyncio
from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient
from strands.models import BedrockModel
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.identity.auth import requires_access_token

logging.basicConfig(level=logging.ERROR, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def invoke_agent(access_token: str) -> None:
    """Invoke agent with access token from ACI"""
    model = BedrockModel(
        model_id=os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        temperature=0.7,
    )
    mcp_client = MCPClient(
        lambda: streamablehttp_client(
            url=os.getenv("AGENTCORE_GW_URL"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
    )
    with mcp_client:
        agent = Agent(
            model=model,
            tools=mcp_client.list_tools_sync()
        )
        response = agent("List all tools available to you")
        result = response.message['content'][0]['text'] + "\n\n"
        response = agent(
            "Check the order status for order id 9999 and "
            "show me the exact response from the tool"
        )
        result += response.message['content'][0]['text']
        # logger.info(result)


@requires_access_token(
    provider_name=os.getenv("ACI_GW_OAUTH2_PROVIDER_NAME"),
    scopes=os.getenv("ACI_GW_OAUTH2_SCOPES").split(","),
    auth_flow='M2M',
)
async def get_token_2lo_async(*, access_token: str) -> None:
    """Retrieves access token using ACI"""
    logger.debug(access_token)
    invoke_agent(access_token)


if __name__ == "__main__":
    asyncio.run(get_token_2lo_async(access_token=""))  # nosec B106
