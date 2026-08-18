"""Custom OTEL span creation"""

# pylint: disable=W1203,W0613

import time
from functools import wraps
from aws_lambda_powertools import Logger
from opentelemetry import trace, baggage, context as otel_context
from opentelemetry.trace import StatusCode
from opentelemetry.propagate import inject

logger = Logger(service="otel_helper")


def inject_otel_headers(request, **kwargs):
    """Inject W3C traceparent, tracestate, baggage, and 
       X-Amzn-Trace-Id headers into boto3 requests."""
    otel_headers = {}
    inject(otel_headers)
    for key, value in otel_headers.items():
        request.headers[key] = value

    # Ensure X-Amzn-Trace-Id always has Sampled=1 so downstream services record the trace
    xray_header = request.headers.get("X-Amzn-Trace-Id", "")
    if xray_header:
        if "Sampled=" not in xray_header:
            request.headers["X-Amzn-Trace-Id"] = f"{xray_header};Sampled=1"
        elif "Sampled=0" in xray_header:
            request.headers["X-Amzn-Trace-Id"] = xray_header.replace("Sampled=0", "Sampled=1")

    logger.info(f"Injected OTel headers: {list(otel_headers.keys())}")
    logger.debug(f"X-Amzn-Trace-Id: {request.headers.get('X-Amzn-Trace-Id', '')}")


def otel_span_decorator(span_name: str = None):
    """
    A decorator to create a custom OpenTelemetry span for a function.
    Gets the tracer at call time to ensure the ADOT TracerProvider is initialized.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get tracer at invocation time (not import time) so ADOT provider is ready
            active_tracer = trace.get_tracer(__name__, "0.1b0")
            with active_tracer.start_as_current_span(span_name or func.__name__) as span:
                span.set_attribute("function.name", func.__name__)
                start_time = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, description=str(e))
                    raise
                finally:
                    end_time = time.perf_counter()
                    span.set_attribute("execution.duration_ms", (end_time - start_time) * 1000)
            # Span is now closed — flush so it's exported before Lambda freezes
            trace.get_tracer_provider().force_flush()
        return wrapper
    return decorator


def attach_baggage_from_event(event: dict) -> None:
    """Extract baggage from gateway request headers and attach to OTel context.

    Only adds baggage entries — does NOT override the existing trace context
    (traceparent/X-Amzn-Trace-Id) set by the ADOT xray-lambda propagator.

    Starts from ctx=None so the active trace parent remains untouched.
    """
    headers = (
        event.get('mcp', {})
        .get('gatewayRequest', {})
        .get('headers', {})
    )
    baggage_header = headers.get('baggage', '')
    if not baggage_header:
        return

    ctx = None
    for item in baggage_header.split(','):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            ctx = baggage.set_baggage(key.strip(), value.strip(), ctx)
    otel_context.attach(ctx)
