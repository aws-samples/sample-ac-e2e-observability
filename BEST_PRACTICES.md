# Best Practices

Observability patterns demonstrated by this project, in the order you should apply them:

1. **[Instrument the Client Application](#instrument-the-client-application)** — start the trace at the true request origin.
2. **[Enable Tracing and Logging for AgentCore Services](#enable-tracing-and-logging-for-agentcore-services)** — capture what happens inside Runtime, Identity, and Gateway.
3. **[Baggage Propagation](#baggage-propagation)** — carry request origin and context across every service boundary.

## Instrument the Client Application

The AgentCore Runtime, Gateway, and tool Lambdas are only part of the request path. The **client application that invokes the Runtime** (a local script, a backend service, an API handler, or another Lambda) is the true origin of every request. If the client is not instrumented, the distributed trace starts at the Runtime boundary and you lose the most important context: *who* made the request, *from where*, and *why*.

The caller Lambda `app/fn_invoke_runtime/call_runtime.py` is the reference implementation. It does three things every instrumented client should do.

**1. Inject the trace context into the outgoing `invoke_agent_runtime` call.**

Register the shared `inject_otel_headers` hook (from `custom_span.py`) on the boto3 client so every AgentCore API call carries the W3C `traceparent`/`tracestate`/`baggage` headers and a sampled `X-Amzn-Trace-Id`. This is what stitches the client span to the downstream Runtime → Gateway → Lambda spans into one trace.

```python
from custom_span import otel_span_decorator, inject_otel_headers

client = boto3.client("bedrock-agentcore", region_name="us-east-1")
# Every API call now carries the current OTel trace context + baggage
client.meta.events.register("before-send.bedrock-agentcore.*", inject_otel_headers)
```

**2. Wrap the invocation in a root span.**

Decorate the function that calls `invoke_agent_runtime` with `@otel_span_decorator` so client-side latency and any pre-processing become the parent span of the entire trace (this is the `call_runtime` span at the root of the [Sample Trace](README.md#sample-trace)).

```python
@otel_span_decorator(span_name="call_runtime")
def call_agent(query, session_id, user_id) -> str:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session_id,
        runtimeUserId=user_id,
        payload=json.dumps({"prompt": query}).encode(),
    )
    ...
```

**3. Set baggage to carry request origin and context.**

Before invoking, attach application-level context as OpenTelemetry baggage. The `inject_otel_headers` hook serializes it into the outgoing `baggage` header, and it flows across every downstream hop — giving each span the origin and context of the request.

```python
from opentelemetry import baggage, context as trace_context

session_id = _session_id()
# Hash PII (user.id) before it leaves the client — baggage is propagated widely
user_id_hashed = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

ctx = baggage.set_baggage("tenant.id", tenant_id)
ctx = baggage.set_baggage("session.id", session_id, ctx)
ctx = baggage.set_baggage("user.id", user_id_hashed, ctx)
trace_context.attach(ctx)

response_str = call_agent(prompt, session_id, user_id)
```

Choose baggage keys that answer "where did this request come from and in what context?" — typically `user.id`, `tenant.id`, `session.id`, and any origin identifiers (calling app, channel, request source). Keep the set small (every key is propagated on every hop) and hash or omit sensitive values.

> **Note:** Only keys in the `OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS` allow-list are copied onto span attributes by the `BaggageSpanProcessor`. Add your origin/context keys there so they appear on downstream spans (see [Required CDK environment variables](#required-cdk-environment-variables)). `session.id` is propagated by convention regardless of the allow-list.

### Instrumenting locally

The same code runs outside Lambda — `call_runtime.py` exposes a `main()` entry point, and `local/invoke.py` is a standalone client — so you can validate instrumentation before deploying. Locally, the ADOT SDK is enabled via the `opentelemetry-instrument` wrapper instead of a Lambda layer:

```bash
uv run --env-file local/.env \
    opentelemetry-instrument \
    python local/invoke.py \
    "Find sushi places near Times Square and get status of order id 42"
```

`local/.env` supplies the ADOT/OTEL configuration the wrapper needs — at minimum:

```bash
AWS_REGION=us-east-1
AGENT_OBSERVABILITY_ENABLED=true
OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS=user.id,tenant.id
# CloudWatch OTLP log delivery (log group/stream must exist)
OTEL_EXPORTER_OTLP_LOGS_HEADERS=x-aws-log-group=<log-group>,x-aws-log-stream=<stream>
OTEL_RESOURCE_ATTRIBUTES=service.name=<your-client>,service.version=1.0
```

With this in place, a locally run client produces the same client-rooted trace as the deployed `call_runtime` Lambda.

## Enable Tracing and Logging for AgentCore Services

Client instrumentation captures the *caller*. To see what happens *inside* each hop you must also turn on traces and logs for the managed AgentCore services themselves — **Runtime, Identity, and Gateway**. In this project that is wired up per resource by two constructs:

- **`AgentCoreTracing`** (`cdk/modules/ac_trace.py`) — delivers `TRACES` to **X-Ray** via `AWS::Logs::DeliverySource → DeliveryDestination → Delivery`.
- **`AgentCoreVendedLog`** (`cdk/modules/ac_vendedlogs.py`) — delivers `APPLICATION_LOGS` to a **CloudWatch Log Group** (`/aws/vendedlogs/bedrock-agentcore/<type>/APPLICATION_LOGS/<id>`).

Both are attached to every AgentCore resource in the stack: the Runtime (`RT-Trace`/`RT-AppLogs`), the MCP Runtime, the Identity credential provider (`ID-Provider-Trace`), the Gateway (`GW-Trace`/`GW-AppLogs`), and the Gateway workload identity (`GW-ID-Trace`/`GW-ID-AppLogs`). Enabling them unlocks two things client spans alone cannot give you: deep **Gateway** request/response and policy logs, and the **Identity** audit chain.

### Gateway: tool discovery, invocation, request/response, and policy logs

Gateway observability makes the full MCP lifecycle and every authorization decision visible:

- **Traces** — `mcp.session` → `AgentCore.Gateway.Initialize`, `mcp tools/list` → `AgentCore.Gateway.ListTools` (tool **retrieval**), and `mcp tools/call` → `AgentCore.Gateway.InvokeTool` (tool **invocation**).
- **Logs** — the `InvokeTool` span carries structured log messages with the raw **request body**, the **policy evaluation** result, and the **response body**.

Request log — shows exactly what the Gateway received, including the propagated baggage (`session.id`, `tenant.id`, hashed `user.id`) and trace context:

```json
{
  "isError": false,
  "log": "Started processing request",
  "requestBody": "{id=2, method=tools/call, params={name=ac-oauth-demo-gwt-orders___get_order_status, _meta={baggage=session.id=runtime_demo_session_20260817_204530,tenant.id=demo_customer_123,user.id=75d9d0ca5449…aef56d1, traceparent=00-6a8372e8…-01}, arguments={orderId=42}}, jsonrpc=2.0}",
  "id": 2
}
```

Policy evaluation log — the decision, the determining policies, the principal, and evaluation latency. This is invaluable for debugging Gateway/policy issues (e.g. an unexpected `DENY` or a policy that never matches):

```json
{
  "isError": false,
  "log": "Policy evaluation completed",
  "id": 2,
  "policy": {
    "decision": "ALLOW",
    "policyEngineArn": "arn:aws:bedrock-agentcore:<region>:<account-id>:policy-engine/ac_oauth_demo_policy-907phqngo2",
    "determiningPolicies": ["allow.all-s.8kjho5gp"],
    "principal": {
      "entityType": "AgentCore::OAuthUser",
      "entityId": "6lipbo************jui6"
    },
    "latencyMs": 43,
    "temporal_evaluation_invoked": false
  }
}
```

> **Tip:** The span header shows the policy engine mode — e.g. **`Policy decision: Log Only Async`** / **`Policy engine mode: Log only`**. In *Log only* mode, decisions are recorded but **not enforced**, so you can validate a new policy against real traffic before switching it to enforcing.

Response log — the tool result the Gateway returned to the agent:

```json
{
  "isError": false,
  "log": "Successfully processed request",
  "id": 2,
  "responseBody": "{jsonrpc=2.0, id=2, result={isError=false, content=[{type=text, text={\"statusCode\":200,\"body\":\"Order Id 42 is in shipped status\"}}]}}"
}
```

### Identity: the user → workload identity → OAuth token (JTI) audit chain

Identity tracing lets an audit team follow a request from the human user all the way to the outbound OAuth token used against a downstream API. Two Identity spans form the chain:

**1. `GetWorkloadAccessTokenForUserId`** maps the end **user** to a **workload identity**:

```json
{
  "request": {
    "associated_resource": "arn:aws:bedrock-agentcore:<region>:<account-id>:runtime/ac_oauth_demo_rt-s1GYPkCOSx",
    "associated_resource_type": "agentcore_runtime",
    "workload_identity": "ac_oauth_demo_rt-s1GYPkCOSx",
    "workload_identity_directory": "default",
    "username": "demo_user_007"
  },
  "response": {
    "response_type": "Success",
    "response_payload": {
      "WorkloadAccessToken": "REDACTED",
      "expires_in": 899,
      "actchain": [{ "workload_identity": "ac_oauth_demo_rt-s1GYPkCOSx" }]
    }
  }
}
```

**2. `GetResourceOauth2Token`** maps the **workload identity** to the **outbound OAuth token**, recording its **JTI** (JWT ID):

```json
{
  "request": {
    "provider_type": "CustomOauth2",
    "credential_provider_name": "ac-oauth-demo-oauth2-provider",
    "oauth2_flow": "M2M",
    "workload_identity": "ac_oauth_demo_rt-s1GYPkCOSx",
    "token_vault": "default"
  },
  "response": {
    "response_type": "Success",
    "response_payload": {
      "AccessToken": "REDACTED",
      "TokenFetched": true,
      "TokenJti": "de7adc8e-a0fa-4237-8ddb-************"
    }
  }
}
```

That gives the full chain: **`demo_user_007` → workload identity `ac_oauth_demo_rt-…` → OAuth token `TokenJti = de7adc8e-a0fa-4237-8ddb-************`**.

#### Pivot from the JTI to every API called with that token

The OAuth token's **JTI** (and `sub`) are stamped on every downstream call the token authorizes, so the JTI is the join key into **CloudTrail data events**. Query CloudTrail (delivered to CloudWatch Logs, or to S3) filtering on `additionalEventData.jwt.claims.jti` to enumerate every API invoked with that token:

```
fields @timestamp, eventName, requestParameters.body.method,
       additionalEventData.jwt.claims.jti, additionalEventData.jwt.claims.sub
| filter additionalEventData.jwt.claims.jti = "de7adc8e-a0fa-4237-8ddb-************"
| sort @timestamp asc
```

Result — every call made with that single token, correlated by `jti` and `sub`:

| @timestamp | eventName | body.method | jwt.claims.jti | jwt.claims.sub |
|---|---|---|---|---|
| 2026-08-17T20:50:49Z | InvokeGateway | initialize | de7adc8e-…-************ | 6lipbo…jui6 |
| 2026-08-17T20:50:49Z | InvokeGateway | notifications/initialized | de7adc8e-…-************ | 6lipbo…jui6 |
| 2026-08-17T20:50:49Z | InvokeGateway | tools/list | de7adc8e-…-************ | 6lipbo…jui6 |
| 2026-08-17T20:50:49Z | InvokeGateway | tools/call | de7adc8e-…-************ | 6lipbo…jui6 |

If CloudTrail is delivered to S3 instead of CloudWatch Logs, run the equivalent filter with Athena (or S3 Select) on the `jwt.claims.jti` field.

> **The three signals correlate on the same identity:** the `TokenJti` in the Identity span equals `additionalEventData.jwt.claims.jti` in CloudTrail, and the CloudTrail `jwt.claims.sub` equals the `principal.entityId` in the Gateway policy log (`6lipbo…jui6`). Traces answer *what happened*, Gateway logs answer *what was allowed*, and CloudTrail answers *what the token did* — all keyed to one user and one token.

> **Masking:** The values above are partially masked for documentation. Real traces/logs contain the full JTI, JWT `sub`, resource ARNs, account ID, and region — treat them as sensitive and restrict access to the trace and log groups accordingly.

## Baggage Propagation

When building distributed traces across AgentCore components, OpenTelemetry [baggage](https://opentelemetry.io/docs/concepts/signals/baggage/) is the mechanism for propagating application-level context (session ID, tenant ID, user ID) across service boundaries. Below are the two patterns used in this project.

### 1. Injecting baggage into outgoing requests (caller side)

On the caller side (`app/fn_invoke_runtime/call_runtime.py`), set baggage on the OTel context before invoking the Runtime; the registered `inject_otel_headers` hook then serializes it into the outgoing `baggage` header. See [Instrument the Client Application](#instrument-the-client-application) for the full client setup.

```python
from opentelemetry import baggage, context as trace_context

# Set baggage entries on the current context
ctx = baggage.set_baggage("tenant.id", tenant_id)
ctx = baggage.set_baggage("session.id", session_id, ctx)
trace_context.attach(ctx)

# The inject_otel_headers boto3 hook adds the baggage header to each call
response = client.invoke_agent_runtime(...)
```

On the receiving service, the ADOT `BaggageSpanProcessor` (configured via the `OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS` allow-list) copies allow-listed baggage keys onto span attributes.

### 2. Parsing incoming baggage in Gateway interceptor Lambdas

Gateway interceptor Lambdas receive the `baggage` header inside the event payload (not as a Lambda transport header), so the ADOT auto-instrumentation does not parse it automatically. You must extract and attach it manually. This project ships that logic as the shared `attach_baggage_from_event` helper in `custom_span.py`, called at the top of `interceptor.lambda_handler`:

```python
from opentelemetry import baggage, context as otel_context

def attach_baggage_from_event(event: dict) -> None:
    """Parse the baggage header from the gateway request and attach to OTel context."""
    headers = event.get('mcp', {}).get('gatewayRequest', {}).get('headers', {})
    baggage_header = headers.get('baggage', '')
    if not baggage_header:
        return

    # Start from None — NOT otel_context.get_current() — to avoid
    # overriding the trace parent (traceparent/X-Amzn-Trace-Id) that
    # the ADOT xray-lambda propagator already set on the Lambda context.
    ctx = None
    for item in baggage_header.split(','):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            ctx = baggage.set_baggage(key.strip(), value.strip(), ctx)
    otel_context.attach(ctx)
```

> **Why `ctx = None` instead of `otel_context.get_current()`?**
>
> The gateway request headers contain both `traceparent` and `baggage`. If you start from `get_current()`, the existing Lambda trace context is correct. However, the `baggage` header also embeds the X-Ray `Self=` segment which, if parsed into the context, can corrupt the span parent chain. Starting from `None` creates a baggage-only context that merges cleanly — the ADOT-managed trace parent remains untouched, and your custom spans stay correctly nested under `interceptor.lambda_handler`.

### Required CDK environment variables

For the `BaggageSpanProcessor` to copy baggage into span attributes, set the allow-list:

```python
"OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS": "session.id,tenant.id,user.id"
```
