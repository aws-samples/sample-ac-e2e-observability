"""Test token retrieval from Agentcore Identity"""
# pylint: disable=C0116

import os
import asyncio
from bedrock_agentcore.identity.auth import requires_access_token

SCOPES = os.getenv("ACI_OAUTH2_SCOPES").split(",")


def main(payload: str, access_token: str) -> None:
    print(payload)
    print(access_token)


# Refer: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-authentication.html
@requires_access_token(
    provider_name=os.getenv("ACI_OAUTH2_PROVIDER_NAME"),
    scopes=SCOPES,
    auth_flow='M2M',
)
async def get_token_2lo_async(*, access_token: str, payload: str) -> None:
    # Make API calls...
    main(payload, access_token)


if __name__ == "__main__":
    asyncio.run(get_token_2lo_async(access_token="", payload="where is my token?"))  # nosec B106
