"""AWS Lambda order tool for AgentCore Gateway MCP demo."""
# pylint: disable=W1203

import json
from typing import Any
from aws_lambda_powertools import Logger
from opentelemetry import trace
from custom_span import otel_span_decorator

TOOL_NAME_DELIMITER = "___"
logger = Logger(service="tool_orders")


def _response(status_code: int, body: str) -> dict[str, Any]:
    """Build a standard Lambda response."""
    return {"statusCode": status_code, "body": body}


def _parse_tool_name(context) -> str:
    """Extract the tool name from the Lambda invocation context."""
    raw = context.client_context.custom["bedrockAgentCoreToolName"]
    logger.debug("Raw tool name: %s", raw)
    if TOOL_NAME_DELIMITER in raw:
        raw = raw.split(TOOL_NAME_DELIMITER, 1)[1]
    logger.info("Resolved tool name: %s", raw)
    return raw


# --- Tool handlers ---
@otel_span_decorator(span_name="get_order_status")
def _get_order_status(event: dict) -> dict[str, Any]:
    status = f"Order Id {event['orderId']} is in shipped status"

    span = trace.get_current_span()
    span.set_attribute("order.status.event", json.dumps(event))
    span.set_attribute("order.status.response", json.dumps(status))

    return _response(200, status)


@otel_span_decorator(span_name="update_order_status")
def _update_order_status(event: dict) -> dict[str, Any]:
    status = f"Updated Order Id {event['orderId']} status to {event['newStatus']}"

    span = trace.get_current_span()
    span.set_attribute("order.status.event", json.dumps(event))
    span.set_attribute("order.status.response", json.dumps(status))

    return _response(200, status)


# Map tool names to their handler functions
_TOOL_DISPATCH: dict[str, callable] = {
    "get_order_status": _get_order_status,
    "update_order_status": _update_order_status,
}


def lambda_handler(event: dict, context) -> dict[str, Any]:
    """Route an AgentCore Gateway tool invocation to the appropriate handler."""
    logger.debug(f"Orders tool event: {event}")
    logger.debug(f"Orders tool context: {context}")

    try:
        tool_name = _parse_tool_name(context)
    except (KeyError, AttributeError):
        logger.exception("Failed to resolve tool name from context")
        return _response(400, "Error: tool name not found in context")

    handler = _TOOL_DISPATCH.get(tool_name)
    if handler is None:
        return _response(400, f"Error: unknown tool '{tool_name}'")

    try:
        return handler(event)
    except KeyError as exc:
        logger.exception(f"Missing required parameter {exc}")
        return _response(400, f"Error: missing required parameter {exc}")
