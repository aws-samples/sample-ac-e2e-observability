# AgentCore Observability Demo

A sample application that deploys a [Strands](https://github.com/strands-agents/sdk-python)-based AI agent on Amazon Bedrock AgentCore Runtime with end-to-end observability. The agent connects to MCP tools through AgentCore Gateway, authenticates via OAuth2 (Cognito) through AgentCore Identity, and emits distributed traces (X-Ray) and application logs (CloudWatch vended logs).

### Observability Best Practices

This project demonstrates a set of observability best practices, documented in detail in [`BEST_PRACTICES.md`](BEST_PRACTICES.md):

- **Instrument the client application** — the caller (`app/fn_invoke_runtime/call_runtime.py`) starts the root span and injects trace context into the `invoke_agent_runtime` call, so traces begin at the true request origin (works both in Lambda and locally via `opentelemetry-instrument`).
- **Propagate origin & context via baggage** — `user.id` (hashed), `tenant.id`, and `session.id` flow across every hop, so each downstream span carries who/where/why.
- **Enable tracing and logging on all AgentCore services** — Runtime, Identity, and Gateway all deliver X-Ray traces and CloudWatch application logs.
- **Use Gateway request/response and policy logs** — see tool discovery/invocation, full request/response bodies, and policy decisions for debugging authorization issues.
- **Follow the Identity audit chain** — trace *user → workload identity → outbound OAuth token (JTI)*, then pivot on the JTI into CloudTrail data events to enumerate every API called with that token.

These practices are backed by **reusable CDK modules** so they can be applied consistently:

- **`InstrumentedLambda`** (`cdk/modules/fn_instrumented.py`) — a base construct that deploys any Lambda with ADOT + Powertools layers, standard OTEL env vars, baggage allow-list, and the required IAM policies. The Orders tool and Gateway interceptor are both built on it.
- **`AgentCoreTracing`** (`cdk/modules/ac_trace.py`) — delivers `TRACES` → X-Ray for any AgentCore resource.
- **`AgentCoreVendedLog`** (`cdk/modules/ac_vendedlogs.py`) — delivers `APPLICATION_LOGS` → a CloudWatch Log Group for any AgentCore resource.

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                                 AWS Account                                           │
│                                                                                       │
│  ┌──────────────┐         ┌─────────────────────────────────────────────────────────┐ │
│  │   Amazon     │         │              Amazon Bedrock AgentCore                   │ │
│  │   Cognito    │         │                                                         │ │
│  │              │         │  ┌──────────────────┐   ┌─────────────────────────┐     │ │
│  │  User Pool   │◀────────│──│    Identity      │   │  Runtime (Agent)        │     │ │
│  │  + M2M       │ OAuth2  │  │  (Token Vault)   │   │  Strands + Claude 4.5   │     │ │
│  │    Client    │         │  │                  │   │                         │     │ │
│  │  + Resource  │         │  │  OAuth2 Provider │   │  - Web Search (DDG)     │     │ │
│  │    Server    │         │  │  Registration    │   │  - MCP Tools via GW     │     │ │
│  └──────────────┘         │  └──────────────────┘   └────────────┬────────────┘     │ │
│                           │          │                            │                 │ │
│                           │          │ Access Token               │ Streamable HTTP │ │
│                           │          ▼                            ▼                 │ │
│                           │  ┌──────────────────────────────────────────────────┐   │ │
│                           │  │                  Gateway                         │   │ │
│                           │  │                                                  │   │ │
│                           │  │  ┌───────────┐  ┌────────────┐  ┌────────────┐   │   │ │
│                           │  │  │Authorizer │  │Interceptor │  │Policy      │   │   │ │
│                           │  │  │ (Cognito) │  │  (Lambda)  │  │Engine      │   │   │ │
│                           │  │  └───────────┘  └────────────┘  └────────────┘   │   │ │
│                           │  │                                                  │   │ │
│                           │  │  ┌────────────────────────────────────────────┐  │   │ │
│                           │  │  │               Targets (MCP)                │  │   │ │
│                           │  │  │                                            │  │   │ │
│                           │  │  │  ┌───────────────────┐ ┌────────────────┐  │  │   │ │
│                           │  │  │  │  Lambda Target    │ │ Runtime Target │  │  │   │ │
│                           │  │  │  │  (Orders Tool)    │ │ (MCP Server)   │  │  │   │ │
│                           │  │  │  │                   │ │                │  │  │   │ │
│                           │  │  │  │ - get_order_      │ │        │       │  │  │   │ │
│                           │  │  │  │   status          │ │        ▼       │  │  │   │ │
│                           │  │  │  │ - update_order_   │ │ ┌────────────┐ │  │  │   │ │
│                           │  │  │  │   status          │ │ │  Runtime   │ │  │  │   │ │
│                           │  │  │  │                   │ │ │(MCP Server)│ │  │  │   │ │
│                           │  │  │  │                   │ │ │            │ │  │  │   │ │
│                           │  │  │  │                   │ │ │ FastMCP +  │ │  │  │   │ │
│                           │  │  │  │                   │ │ │ Weather    │ │  │  │   │ │
│                           │  │  │  │                   │ │ │ Tool       │ │  │  │   │ │
│                           │  │  │  │                   │ │ └────────────┘ │  │  │   │ │
│                           │  │  │  └───────────────────┘ └────────────────┘  │  │   │ │
│                           │  │  └────────────────────────────────────────────┘  │   │ │
│                           │  └──────────────────────────────────────────────────┘   │ │
│                           └─────────────────────────────────────────────────────────┘ │
│                                                                                       │
│  ┌──────────────────────────────────────────────────────────────────────────────┐     │
│  │                           Observability                                      │     │
│  │                                                                              │     │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────────┐  │     │
│  │  │  CloudWatch Logs │  │     X-Ray        │  │    Online Evaluation       │  │     │
│  │  │  (Vended Logs)   │  │   (Traces)       │  │    (Built-in Metrics)      │  │     │
│  │  │                  │  │                  │  │                            │  │     │
│  │  │  - Runtime logs  │  │  - Runtime       │  │  - Goal Success Rate       │  │     │
│  │  │  - Gateway logs  │  │  - Gateway       │  │  - Helpfulness             │  │     │
│  │  │  - MCP Srv logs  │  │  - MCP Server    │  │  - Correctness             │  │     │
│  │  │                  │  │  - Identity      │  │  - Response Relevance      │  │     │
│  │  │                  │  │                  │  │  - Harmfulness             │  │     │
│  │  │                  │  │                  │  │  - Tool Selection Accuracy │  │     │
│  │  │                  │  │                  │  │  - Tool Parameter Accuracy │  │     │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────────┘  │     │
│  └──────────────────────────────────────────────────────────────────────────────┘     │
│                                                                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### Component Summary

| Component | Purpose |
|-----------|---------|
| **AgentCore Runtime (Agent)** | Hosts a Strands agent container with Claude Sonnet 4.5, DuckDuckGo web search, and MCP tool access via Gateway |
| **AgentCore Runtime (MCP Server)** | Hosts a FastMCP-based MCP server (Streamable HTTP) as a Gateway target, demonstrating Runtime as a tool backend |
| **AgentCore Gateway** | MCP-compliant gateway that routes tool calls to Lambda or Runtime targets with Cognito authorization, request/response interceptors, and a policy engine |
| **AgentCore Identity** | Registers Cognito OAuth2 credentials so the agent Runtime can obtain access tokens for Gateway (M2M flow) |
| **Amazon Cognito** | Provides OAuth2 M2M authentication via a User Pool, Resource Server with custom scopes, and a client credentials grant |
| **Lambda – Orders Tool** | MCP tool target handling `get_order_status` and `update_order_status` |
| **Lambda – Interceptor** | Pass-through interceptor that logs MCP requests and responses for debugging |
| **Observability** | X-Ray distributed traces, CloudWatch vended logs, and online evaluation (goal success rate, helpfulness, correctness, response relevance, harmfulness, and tool selection/parameter accuracy) across all AgentCore components |

### Request Flow

1. A client invokes the **Runtime** with a prompt.
2. The Strands agent reasons over the prompt using **Claude Sonnet 4.5**.
3. The agent requests an OAuth2 access token from **AgentCore Identity** (backed by Cognito).
4. The agent connects to the **Gateway** over Streamable HTTP (MCP protocol) with the bearer token.
5. The Gateway **authorizer** validates the token against Cognito.
6. The Gateway **interceptor** logs the request, then forwards it to the appropriate target (Lambda or Runtime MCP Server).
7. The response flows back through the interceptor and Gateway to the agent.
8. All components emit **traces** (X-Ray) and **application logs** (CloudWatch vended logs).

### Sample Trace

A representative X-Ray distributed trace for a single agent invocation. It shows the full request lifecycle across Runtime, Identity, Gateway, and Lambda.

```
call_runtime.lambda_handler                                                       22.62s
└── call_runtime                                                                  22.61s
    └── Bedrock AgentCore.InvokeAgentRuntime                                       1.53s
        └── AgentCore.Runtime.Invoke                                               1.13s
            ├── Bedrock.AgentCore.Identity.GetWorkloadAccessTokenForUserId            0s
            └── POST /invocations                                                 21.10s
                ├── Bedrock AgentCore.GetResourceOauth2Token                       0.66s
                │   └── Bedrock.AgentCore.Identity.GetResourceOauth2Token             0s
                ├── mcp.session                                                   20.30s
                │   ├── AgentCore.Gateway.Initialize                               2.52s
                │   └── AgentCore.Gateway.NotificationsInitialized                 0.28s
                ├── mcp tools/list                                                 0.71s
                │   └── AgentCore.Gateway.ListTools                                0.39s
                └── invoke_agent Strands Agents               [6,085→604 tokens]  17.03s
                    ├── execute_event_loop_cycle                                   5.30s
                    │   └── chat                              [1,049→111 tokens]   2.87s
                    │       └── chat us.anthropic.claude-sonnet-4-5-20250929-v1:0  2.87s
                    ├── execute_tool web_search                                    1.63s
                    ├── execute_tool ac-oauth-demo-gwt-orders___get_order_status   2.43s
                    │   └── mcp tools/call ...get_order_status                     2.43s
                    │       └── AgentCore.Gateway.InvokeTool                       2.41s
                    │           ├── interceptor.lambda_handler                        0s
                    │           │   └── gateway_request_intercept                     0s
                    │           ├── AgentCore.Gateway.InvokeTool.ac-oauth-demo     2.14s
                    │           ├── orders.lambda_handler                          0.01s
                    │           │   └── get_order_status                              0s
                    │           └── interceptor.lambda_handler                        0s
                    │               └── gateway_response_intercept                    0s
                    ├── execute_event_loop_cycle                                   6.17s
                    │   └── chat                              [1,699→195 tokens]   4.60s
                    ├── execute_tool web_search ×3                                 1.56s
                    └── execute_event_loop_cycle                                   5.57s
                        └── chat                              [3,337→298 tokens]   5.56s
```

**Key observations:**

- **Root span** is the client-side invoker Lambda (`call_runtime.lambda_handler`), which drives `InvokeAgentRuntime`.
- **Identity token fetch** (`GetResourceOauth2Token`) takes ~0.66 s and occurs once per session.
- **MCP session setup** (`mcp.session`) covers `Gateway.Initialize` and `NotificationsInitialized` before tools are usable.
- **Gateway tool discovery** (`ListTools`) resolves the available tools (~0.39 s).
- **Tool execution** flows through Gateway → request interceptor → tool Lambda → response interceptor, each visible as a span (`interceptor.lambda_handler`, `orders.lambda_handler`).
- **LLM calls** include token counts (input → output) and per-cycle latency; each `chat` wraps a model-specific span.
- **Multi-cycle reasoning** — the agent runs three event-loop cycles before composing its final answer.
- **Repeated tool calls** — `web_search` is invoked multiple times, including `web_search ×3` within a single cycle.

## Prerequisites

1. An AWS account.
2. Permissions to create, modify, and delete the following AWS services:
    - Amazon Cognito
    - AWS Lambda
    - Amazon Bedrock AgentCore components
    - Amazon CloudWatch (log groups, streams, metrics, and transaction search)
    - AWS IAM roles and policies

## Setup

### 1. Clone this repository

```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. Install dependencies

```bash
uv sync --refresh --reinstall
uv sync --all-extras

```

### 3. Deploy the AgentCore stack

Make sure AWS credentials with the required permissions are configured in your CLI.

Copy `cdk/.env.cdk.sample` to `cdk/.env` and set the CDK context to be used.

1. To opt out of ADOT GenAI content extraction (prevents prompt/completion content from being captured in traces) set `AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT=true`
2. To enable experimental OpenTelemetry GenAI semantic conventions on the agent `OTEL_SEMCONV_STABILITY_OPT_IN=true`
3. To attach the Lambda request interceptor to the AgentCore Gateway set `ENABLE_GW_REQUEST_INTERCEPTOR=true` (default: `false`)
4. To attach the Lambda response interceptor to the AgentCore Gateway set `ENABLE_GW_RESPONSE_INTERCEPTOR=true` (default: `false`)

```bash
cd cdk
uv run --env-file .env cdk deploy
```


### 4. Invoke the agent end-to-end

Navigate to AWS Lambda function for call runtime and use sample JSON below to invoke the agent.
```json
{
  "tenant.id": "demo_customer_123",
  "user.id": "demo_user_007",
  "prompt": "Find the weather and sushi places near Times Square and get status of order id 42"
}
```

### 5. Clean-up AgentCore stack

Clean-up all AWS resources created in this project

```bash
cd cdk
uv run --env-file .env cdk destroy
```

## Optional scripts to invoke and test from local terminal

### Run unit tests

```bash
uv run pytest
```

### Invoke runtime from local terminal


Copy `local/.env.sample` to `local/.env` and populate it with CDK stack output values.

```bash
uv run --env-file local/.env \
    opentelemetry-instrument \
    python local/invoke.py \
    "Find sushi places near Times Square and get status of order id 42"
```

Alternatively, without instrumentation (omit the `opentelemetry-instrument` wrapper):

```bash
uv run --env-file local/.env \
    python local/invoke.py \
    "Find sushi places near Times Square and get status of order id 42"
```

### Run the Strands agent locally invoking gateway with M2M OAuth

```bash
uv run --env-file local/.env local/local_agent.py
```

> **Note:** If you see `[ERROR] client failed to initialize` (surfacing as
> `MCPClientInitializationError: ... Session terminated`), check that
> `AGENTCORE_GW_URL` in `local/.env` matches your current gateway. The gateway
> URL changes whenever the gateway is recreated, so a stale value points to a
> gateway that no longer exists and the endpoint returns HTTP 404. Look up the
> current URL with:
>
> ```bash
> aws bedrock-agentcore-control list-gateways --region us-east-1 \
>     --query 'items[?name==`ac-oauth-demo-gw`].{id:gatewayId,status:status}' --output table
> aws bedrock-agentcore-control get-gateway --region us-east-1 \
>     --gateway-identifier <gatewayId> --query gatewayUrl --output text
> ```
>
> Update `AGENTCORE_GW_URL` in `local/.env` with the returned URL (it must end in `/mcp`).


### Test OAuth2 M2M token retrieval

**Directly via the Cognito token endpoint:**

Copy `local/.env.cognito.sample` to `local/.env.cognito` and fill in the values (the Client Secret is available in the Cognito console).

```bash
uv run --env-file local/.env.cognito local/cognito_token.py
```

**Via AgentCore Identity:**

Copy `local/.env.aci.sample` to `local/.env.aci` and fill in the values.

```bash
uv run --env-file local/.env.aci local/aci_token.py
```

## Project Structure

```
.
├── app/                            # Application source (agent, MCP server, Lambdas)
│   ├── agent/                      # Strands agent deployed to AgentCore Runtime
│   │   ├── agent.py                # Culinary Assistant agent logic, tools, MCP integration
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── mcp/                        # FastMCP server deployed to AgentCore Runtime (GW target)
│   │   ├── weather.py              # Weather tool served via Streamable HTTP
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── fn_tool_orders/             # Orders MCP tool Lambda
│   │   └── orders.py               # Orders tool handler
│   ├── fn_gw_intercept/            # Gateway interceptor Lambda
│   │   └── interceptor.py          # Pass-through gateway request/response interceptor
│   ├── fn_invoke_runtime/          # Runtime invocation Lambda
│   │   └── call_runtime.py         # Invokes the AgentCore Runtime
│   └── fn_shared/                  # Shared Lambda layer
│       └── python/
│           └── custom_span.py      # Custom OTEL span decorator
├── cdk/                            # CDK infrastructure
│   ├── app.py                      # CDK app entry point
│   ├── stacks/
│   │   └── ac_obs_demo_stack.py    # Root stack composing all constructs
│   ├── modules/                    # CDK constructs
│   │   ├── cognito_upool.py        # Cognito User Pool + M2M client
│   │   ├── ac_gw.py                # AgentCore Gateway + targets
│   │   ├── ac_gw_workload_id.py    # Gateway Workload Identity ARN (custom resource)
│   │   ├── ac_identity.py          # AgentCore Identity (OAuth2 provider)
│   │   ├── ac_runtime.py           # AgentCore Runtime (Agent)
│   │   ├── ac_rt_mcp.py            # AgentCore Runtime (MCP Server)
│   │   ├── ac_trace.py             # X-Ray trace delivery
│   │   ├── ac_vendedlogs.py        # CloudWatch vended log delivery
│   │   ├── fn_instrumented.py      # Reusable instrumented Lambda construct
│   │   └── fn_layer_shared.py      # Shared Lambda layer construct
│   └── schemas/
│       └── orders-tool.json        # Orders tool schema (GW target)
└── local/                          # Client scripts and environment files
    ├── invoke.py                   # Invoke runtime and parse streaming response events
    ├── local_agent.py              # Strands agent invoking gateway with M2M OAuth
    ├── aci_token.py                # Test token retrieval via AgentCore Identity
    └── cognito_token.py            # Retrieve access token from Cognito directly
```

## Other Useful Commands

### Set up UV

```bash
uv venv --python 3.13 --clear
uv init
uv add --dev -r requirements-cdk.txt
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
