"""Invoke runtime"""
# pylint:disable=W1203,W0718

import os
import json
import hashlib
from typing import Any
from datetime import datetime
import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from opentelemetry import baggage, context as trace_context
from custom_span import otel_span_decorator, inject_otel_headers

RUNTIME_ARN = os.getenv("RUNTIME_ARN")

logger = Logger(service="call_runtime")
client = boto3.client("bedrock-agentcore", region_name="us-east-1")

# Register the event hook so every API call carries the trace context
client.meta.events.register("before-send.bedrock-agentcore.*", inject_otel_headers)


def _session_id() -> str:
    """Generate custom agent session id"""
    # Session ID must be ≥33 chars
    return f"runtime_demo_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _response(status_code: int, body: str) -> dict[str, Any]:
    """Build a standard Lambda response."""
    return {"statusCode": status_code, "body": body}


@otel_span_decorator(span_name="call_runtime")
def call_agent(query, session_id, user_id) -> str:
    """Call runtime agent and prints response"""
    logger.info(f"[SessionID={session_id}] {query}")

    payload = json.dumps({"prompt": query}).encode()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        payload=payload,
    )

    # Process and print the response
    content = []
    if "text/event-stream" in response.get("contentType", ""):
        # Handle streaming response
        for line in response["response"].iter_lines(chunk_size=10):
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                    logger.debug(line)
                    content.append(line)
        return "\n".join(content)

    if response.get("contentType") == "application/json":
        # Handle standard JSON response
        for chunk in response.get("response", []):
            delta = chunk.decode('utf-8')
            logger.debug(delta)
            content.append(delta)
        return json.loads(''.join(content))

    return ""


def lambda_handler(event: dict, context: LambdaContext) -> dict[str, Any]:
    """Invoke runtime agent"""
    logger.debug("Boto3 version: %s", boto3.__version__)
    logger.debug("Event: %s", json.dumps(event, default=str))
    logger.debug("Context: %s", json.dumps(context.__dict__, default=str))

    # Extract prompt and tenant.id from event, falling back to defaults
    prompt = (event or {}).get(
        "prompt",
        "Find sushi places near Times Square and get status of order id 42"
    )
    tenant_id = (event or {}).get("tenant.id", "customer_xyz")
    user_id = (event or {}).get("user.id", "user_xyz")
    user_id_hashed = hashlib.sha256(user_id.encode('utf-8')).hexdigest()

    session_id = _session_id()
    ctx = baggage.set_baggage("tenant.id", tenant_id)
    ctx = baggage.set_baggage("session.id", session_id, ctx)
    ctx = baggage.set_baggage("user.id", user_id_hashed, ctx)
    trace_context.attach(ctx)

    response_str = call_agent(prompt, session_id, user_id)
    return _response(200, response_str)


def main():
    """Main routine to make multi-turn query"""
    session_id = _session_id()
    call_agent(
        "Find sushi places near Times Square and get status of order id 42",
        session_id,
        "user_xyz"
    )


if __name__ == "__main__":
    main()
