"""Retrieve access token from Cognito directly"""

import os
import logging
import httpx


logging.basicConfig(level=logging.ERROR, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_oauth_bearer_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    scope: str,
    timeout: float = 10.0,
) -> dict:
    """Retrieve OAuth bearer token using client credentials grant."""
    response = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "scope": scope,
        },
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    """Main entry point"""
    try:
        token = get_oauth_bearer_token(
            token_url=os.getenv("COGNITO_TOKEN_ENDPOINT"),
            client_id=os.getenv("COGNITO_CLIENT_ID"),
            client_secret=os.getenv("COGNITO_CLIENT_SECRET"),
            scope=os.getenv("COGNITO_SCOPE", ""),
        )
        print(token)
    except httpx.HTTPStatusError as exc:
        # nosemgrep: python.lang.security.audit.logging.python-logger-credential-disclosure
        logger.error("Token request failed with status %d", exc.response.status_code)
    except KeyError as exc:
        logger.error("Missing environment variable: %s", exc)


if __name__ == "__main__":
    main()
