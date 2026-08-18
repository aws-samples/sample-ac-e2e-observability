
"""Simple pass-through GW interceptor"""

# pylint: disable=W1203
import json
from aws_lambda_powertools import Logger
from opentelemetry import trace
from custom_span import otel_span_decorator, attach_baggage_from_event


# Configure logging
logger = Logger(service="gateway_interceptor")


@otel_span_decorator(span_name="gateway_request_intercept")
def gateway_request_intercept(mcp_data: dict) -> dict:
    """Gateway REQUEST interceptor"""
    gateway_request = mcp_data.get('gatewayRequest', {})
    request_body = gateway_request.get('body', {})
    mcp_method = request_body.get('method', 'unknown')

    # Set span attributes for observability
    span = trace.get_current_span()
    span.set_attribute("gateway.request.body", json.dumps(request_body))

    # Log the MCP method
    logger.info(f"Processing REQUEST interceptor - MCP method: {mcp_method}")

    # Pass through the original request unchanged
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayRequest": {
                "body": request_body,
            }
        }
    }


@otel_span_decorator(span_name="gateway_response_intercept")
def gateway_response_intercept(mcp_data: dict) -> dict:
    """Gateway RESPONSE interceptor"""
    request_body = mcp_data.get('gatewayRequest', {}).get('body', {})
    response_body = mcp_data.get('gatewayResponse', {}).get('body', {})
    status_code = mcp_data.get('gatewayResponse', {}).get('statusCode', 200)
    mcp_method = request_body.get('method', 'unknown')

    # Set span attributes for observability
    span = trace.get_current_span()
    span.set_attribute("gateway.request.body", json.dumps(request_body))
    span.set_attribute("gateway.response.body", json.dumps(response_body))
    span.set_attribute("gateway.response.status_code", status_code)

    logger.info(f"Processing RESPONSE interceptor - MCP method: {mcp_method}")

    # Pass through the original request and response unchanged
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {
            "transformedGatewayResponse": {
                "body": response_body,
                "statusCode": status_code
            }
        }
    }


def lambda_handler(event, context):
    """
    Lambda function that handles both REQUEST and RESPONSE interceptor types.

    For REQUEST interceptors: logs the MCP method and passes request through unchanged
    For RESPONSE interceptors: passes response through unchanged
    """
    logger.debug(f"Intercept event: {event}")
    logger.debug(f"Intercept context: {context}")

    # Extract baggage from gateway request headers into OTel context
    attach_baggage_from_event(event)

    # Extract the MCP data from the event
    mcp_data = event.get('mcp', {})

    # Check if this is a REQUEST or RESPONSE interceptor based on presence of gatewayResponse
    if 'gatewayResponse' in mcp_data and mcp_data['gatewayResponse'] is not None:
        response = gateway_response_intercept(mcp_data)
    else:
        response = gateway_request_intercept(mcp_data)

    return response
