"""Invoke demo runtime and parse streaming response events."""

# pylint: disable = W1203

import json
import os
import re
import sys
import logging
import time
import boto3

from opentelemetry import baggage, context as trace_context
from custom_span import otel_span_decorator


RUNTIME_ARN = os.getenv("AGENTCORE_RUNTIME_ARN")
REGION = os.getenv("AWS_REGION", "us-east-1")
APP_NAME = os.getenv("APP_NAME")

# Logging config
logging.basicConfig(level=logging.ERROR, format="[%(asctime)s][%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# boto3 client initialize
client = boto3.client("bedrock-agentcore", region_name=REGION)


def parse_sse_chunk(raw: str) -> None:
    """Parse SSE data lines from a raw chunk and print/collect text."""
    for part in re.split(r'(?:^|\n)data: ', raw):
        part = part.strip()
        if not part:
            continue
        try:
            data = json.loads(part)
            text = data.get("text", part) if isinstance(data, dict) else str(data)
        except (json.JSONDecodeError, TypeError):
            text = part
        sys.stdout.write(text)
        sys.stdout.flush()


def set_otel_context(user_id):
    """User ID OpenTelemetry baggage for distributed trace correlation"""
    ctx = baggage.set_baggage("user.id", user_id)
    ctx = baggage.set_baggage("tenant.id", "customer_xyz", ctx)
    token = trace_context.attach(ctx)
    logger.info(f"User ID context baggage '{user_id}' attached")
    return token


@otel_span_decorator(span_name="ac-demo")
def invoke(prompt: str, user_id: str = "demo_user_1234") -> str:
    """Invoke the agent runtime and stream response events in real time."""
    print("[Starting] " + "-" * 80)
    logger.info(f"Invoking agent [{user_id}]: {prompt}")
    start = time.perf_counter()
    # set_otel_context(user_id)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeUserId=user_id,
        payload=json.dumps({"prompt": prompt}),
    )

    # Print trace ID from response headers
    for k, v in response.items():
        if k in [
                "traceId", "traceParent", "traceState", "baggage",
                "mcpSessionId", "runtimeSessionId"]:
            logger.debug(f"[{k}] {v}")
    print()
    print("[Agent response] " + "-" * 80)

    event_stream = response.get("response")

    # Try reading as a raw streaming body (real-time line-by-line)
    raw_stream = getattr(event_stream, "_raw_stream", None)
    if raw_stream and hasattr(raw_stream, "stream"):
        # Read from the underlying urllib3/botocore stream
        buffer = ""
        for chunk in raw_stream.stream(amt=256):
            decoded = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            buffer += decoded
            # Process complete SSE lines (ending with newline)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line.startswith("data: "):
                    line = line[6:]
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    text = data.get("text", line) if isinstance(data, dict) else str(data)
                except (json.JSONDecodeError, TypeError):
                    text = line
                sys.stdout.write(text)
                sys.stdout.flush()
        # Flush remaining buffer
        if buffer.strip():
            parse_sse_chunk(buffer)
    else:
        # Fallback: iterate EventStream events
        for event in event_stream:
            if isinstance(event, (bytes, bytearray)):
                decoded = event.decode("utf-8")
            elif isinstance(event, dict):
                if "chunk" in event:
                    payload = event["chunk"].get("bytes", b"")
                    decoded = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
                else:
                    continue
            else:
                decoded = str(event)
            parse_sse_chunk(decoded)
    elapsed = time.perf_counter() - start
    print()
    print("[Completed] " + "-" * 80)
    logger.info(f"Agent completed. Elapsed: {elapsed:.2f}s")
    print()


def main() -> None:
    """Main entry point."""
    prompt = " ".join(sys.argv[1:]) or "Find sushi places in NYC and get status of order id 42"
    user_id = "demo_user_42"
    set_otel_context(user_id)
    invoke(prompt, user_id)


if __name__ == "__main__":
    main()
