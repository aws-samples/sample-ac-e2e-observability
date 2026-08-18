"""CDK application stack for the AgentCore Observability Demo.

This stack wires together a full Amazon Bedrock AgentCore application. Read the
steps below top-to-bottom to understand how the pieces connect:

    Step 1  Shared Lambda layer  - common OTEL helper code for every Lambda.
    Step 2  Tool + interceptor Lambdas - the Orders MCP tool and the Gateway
            request/response interceptor (both instrumented for tracing).
    Step 3  Cognito user pool      - OAuth2 M2M identity provider (issues tokens).
    Step 4  AgentCore Identity     - registers the Cognito client with the
            AgentCore Token Vault so services can mint OAuth tokens.
    Step 5  AgentCore Gateway      - MCP-compliant gateway that fronts all tools.
    Step 6  Orders Lambda target   - registers the Orders Lambda on the gateway.
    Step 7  MCP Runtime + target   - a FastMCP server on AgentCore Runtime,
            registered as a second gateway target (OAuth-authenticated).
    Step 8  Gateway IAM grants     - lets the gateway fetch OAuth tokens/secrets.
    Step 9  Agent Runtime          - the Strands agent that calls the gateway.
    Step 10 Caller Lambda          - a client Lambda that invokes the agent.

Auth model in one line: everything speaks Cognito OAuth2 (M2M). The gateway and
the MCP runtime both trust the same Cognito pool; AgentCore Identity mints the
tokens; IAM policies let each principal fetch those tokens.
"""

from pathlib import Path
from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    Fn,
    aws_iam as iam,
    aws_bedrockagentcore as _agentcore,
)
from constructs import Construct
from modules.cognito_upool import CognitoUserPool
from modules.ac_gw import AgentCoreGateway
from modules.ac_identity import AgentCoreIdentity
from modules.ac_runtime import AgentCoreRuntime
from modules.ac_rt_mcp import AgentCoreRuntimeMCP
from modules.fn_instrumented import InstrumentedLambda
from modules.fn_layer_shared import FnSharedLayer

_SCHEMAS_DIR = Path(__file__).resolve().parent / ".." / "schemas"


class ACObsDemoStack(Stack):
    """Deploys the complete AgentCore observability demo application."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Step 1: Shared Lambda layer -------------------------------------
        # Holds the OTEL custom-span helpers imported by every Lambda so the
        # code lives in exactly one place.
        shared_layer = FnSharedLayer(self, "SharedLayer")

        # --- Step 2: Tool and interceptor Lambdas ----------------------------
        # The Orders tool is the actual MCP tool the agent calls. The gateway
        # interceptor logs/annotates every request and response flowing through
        # the gateway. Both use the shared layer and are ADOT-instrumented.
        orders_tool = InstrumentedLambda(
            self, "OrdersTool",
            handler="orders.lambda_handler",
            code_path="app/fn_tool_orders",
            shared_layer=shared_layer.layer,
            description="Lambda based MCP tool for Orders",
        )
        gw_interceptor = InstrumentedLambda(
            self, "GWIntercept",
            handler="interceptor.lambda_handler",
            code_path="app/fn_gw_intercept",
            shared_layer=shared_layer.layer,
            description="Lambda gateway interceptor",
        )

        # --- Step 3: Cognito user pool ---------------------------------------
        # Provides OAuth2 machine-to-machine (M2M) authentication. Every other
        # component trusts tokens issued by this pool.
        cognito_upool = CognitoUserPool(self, "Cognito")

        # --- Step 4: AgentCore Identity --------------------------------------
        # Registers the Cognito client with the AgentCore Token Vault. This is
        # what lets the gateway (and agent) later request OAuth tokens on demand.
        aci = self._create_identity(cognito_upool)

        # --- Step 5: AgentCore Gateway ---------------------------------------
        # MCP-compliant gateway. Clients connect here; it authorizes them
        # against Cognito and forwards tool calls to registered targets.
        # The request/response interceptors are opt-in via CDK context
        # (ENABLE_GW_REQUEST_INTERCEPTOR / ENABLE_GW_RESPONSE_INTERCEPTOR),
        # which can be set through the CDK env file. Both default to false.
        enable_request_interceptor = self._context_flag("ENABLE_GW_REQUEST_INTERCEPTOR")
        enable_response_interceptor = self._context_flag("ENABLE_GW_RESPONSE_INTERCEPTOR")
        acgw = AgentCoreGateway(
            self, "MCP",
            upool=cognito_upool,
            request_interceptor_fn=(
                gw_interceptor.function if enable_request_interceptor else None
            ),
            response_interceptor_fn=(
                gw_interceptor.function if enable_response_interceptor else None
            ),
        )

        # --- Step 6: Register the Orders Lambda as a gateway target ----------
        self._add_orders_target(acgw, orders_tool)

        # --- Step 7: MCP Runtime + register it as a second gateway target ----
        self._add_mcp_runtime_target(acgw, aci, cognito_upool)

        # --- Step 8: Grant the gateway role the permissions it needs ---------
        # So it can mint OAuth tokens and read the client secret when talking
        # to the OAuth-authenticated MCP Runtime target.
        self._grant_gateway_oauth_permissions(acgw)

        # --- Step 9: Agent Runtime -------------------------------------------
        # The Strands agent. It connects to the gateway (using an OAuth token
        # from AgentCore Identity) to reach all the tools.
        runtime = AgentCoreRuntime(
            self, "RT",
            gateway_url=acgw.gateway.gateway_url,
            gateway_oauth2_provider_name=aci.name,
        )

        # --- Step 10: Caller Lambda ------------------------------------------
        # A simple client that invokes the agent runtime end-to-end.
        self._add_caller_lambda(shared_layer, runtime)

    # ------------------------------------------------------------------ #
    # Context helper
    # ------------------------------------------------------------------ #
    def _context_flag(self, key: str, default: bool = False) -> bool:
        """Read a boolean CDK context flag (defaults to False).

        Context values sourced from the CDK env file arrive as strings, so a
        value of "true" (case-insensitive) is treated as True and anything
        else as False.
        """
        value = self.node.try_get_context(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() == "true"

    # ------------------------------------------------------------------ #
    # Step 4 helper
    # ------------------------------------------------------------------ #
    def _create_identity(self, cognito_upool: CognitoUserPool) -> AgentCoreIdentity:
        """Register the Cognito OAuth2 client with AgentCore Identity."""
        discovery_url = (
            f"https://cognito-idp.{self.region}.amazonaws.com/"
            f"{cognito_upool.user_pool.user_pool_id}"
            "/.well-known/openid-configuration"
        )
        return AgentCoreIdentity(
            self, "Identity",
            vendor="CustomOauth2",
            provider_config={
                "customOauth2ProviderConfig": {
                    "oauthDiscovery": {"discoveryUrl": discovery_url},
                    "clientId": cognito_upool.user_pool_client.user_pool_client_id,
                    "clientSecret": (
                        cognito_upool.user_pool_client
                        .user_pool_client_secret.unsafe_unwrap()
                    ),
                }
            },
        )

    # ------------------------------------------------------------------ #
    # Step 6 helper
    # ------------------------------------------------------------------ #
    def _add_orders_target(
        self,
        acgw: AgentCoreGateway,
        orders_tool: InstrumentedLambda,
    ) -> None:
        """Register the Orders Lambda as an MCP tool target on the gateway."""
        # The tool schema (tool names + input JSON schema) is loaded from a file.
        orders_tool_schema = _agentcore.ToolSchema.from_local_asset(
            str(_SCHEMAS_DIR / "orders-tool.json")
        )
        orders_target = acgw.gateway.add_lambda_target(
            "OrdersToolTarget",
            gateway_target_name=f"{self.stack_name}-gwt-orders",
            description="Orders Lambda function target",
            lambda_function=orders_tool.function,
            tool_schema=orders_tool_schema,
        )
        CfnOutput(
            self, "orders_acgw_target_id",
            description="Orders tool Agentcore Gateway Target ID",
            value=orders_target.target_id,
        )

    # ------------------------------------------------------------------ #
    # Step 7 helper
    # ------------------------------------------------------------------ #
    def _add_mcp_runtime_target(
        self,
        acgw: AgentCoreGateway,
        aci: AgentCoreIdentity,
        cognito_upool: CognitoUserPool,
    ) -> None:
        """Deploy the MCP Runtime and register it as a gateway MCP-server target.

        The MCP Runtime uses Cognito JWT inbound auth so the gateway can present
        an OAuth bearer token. (SigV4 would require an X-...-User-Id header the
        gateway can't supply, which fails with an authorization error.)
        """
        rt_mcp = AgentCoreRuntimeMCP(self, "RTMCP", upool=cognito_upool)

        # Build the MCP invocation endpoint URL for the runtime. The runtime ARN
        # is a CDK token, so we URL-encode it at deploy time: ':' -> '%3A' and
        # '/' -> '%2F' using nested Fn.split/Fn.join.
        mcp_runtime_arn = rt_mcp.mcp_runtime.agent_runtime_arn
        encoded_arn = Fn.join(
            "%2F",
            Fn.split("/", Fn.join("%3A", Fn.split(":", mcp_runtime_arn))),
        )
        mcp_endpoint = (
            f"https://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/"
            f"{encoded_arn}/invocations?qualifier=DEFAULT"
        )

        # The gateway authenticates to the runtime with an OAuth bearer token
        # minted by AgentCore Identity (Cognito M2M client-credentials flow),
        # scoped to the gateway resource server's read/write scopes.
        mcp_scopes = [
            f"{self.stack_name}-acgw-rs/gateway:read",
            f"{self.stack_name}-acgw-rs/gateway:write",
        ]
        mcp_target = _agentcore.CfnGatewayTarget(
            self, "McpRuntimeTarget",
            name=f"{self.stack_name}-gwt-mcp-rt",
            description="MCP Runtime server target",
            gateway_identifier=acgw.gateway.gateway_id,
            target_configuration=_agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=_agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    mcp_server=_agentcore.CfnGatewayTarget.McpServerTargetConfigurationProperty(
                        endpoint=mcp_endpoint,
                    )
                )
            ),
            credential_provider_configurations=[
                _agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="OAUTH",
                    credential_provider=_agentcore.CfnGatewayTarget.CredentialProviderProperty(
                        oauth_credential_provider=_agentcore.CfnGatewayTarget.OAuthCredentialProviderProperty(
                            provider_arn=aci.credential_provider_arn,
                            scopes=mcp_scopes,
                            grant_type="CLIENT_CREDENTIALS",
                        )
                    ),
                )
            ],
        )
        # The runtime must exist before the gateway tries to connect to it.
        mcp_target.node.add_dependency(rt_mcp)
        CfnOutput(
            self, "mcp_rt_acgw_target_id",
            description="MCP Runtime Agentcore Gateway Target ID",
            value=mcp_target.attr_target_id,
        )

    # ------------------------------------------------------------------ #
    # Step 8 helper
    # ------------------------------------------------------------------ #
    def _grant_gateway_oauth_permissions(self, acgw: AgentCoreGateway) -> None:
        """Give the gateway role the permissions to use OAuth-based targets."""
        # Fetch OAuth tokens from the AgentCore Identity token vault.
        acgw.gateway.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:GetResourceOauth2Token"],
                resources=["*"],
            )
        )
        # Read the OAuth client secret AgentCore Identity stores in Secrets
        # Manager (the '!' marks it as an AWS-managed secret).
        acgw.gateway.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}"
                    ":secret:bedrock-agentcore-identity!default/oauth2/*",
                ],
            )
        )

    # ------------------------------------------------------------------ #
    # Step 10 helper
    # ------------------------------------------------------------------ #
    def _add_caller_lambda(
        self,
        shared_layer: FnSharedLayer,
        runtime: AgentCoreRuntime,
    ) -> None:
        """Deploy a client Lambda that invokes the agent runtime end-to-end."""
        InstrumentedLambda(
            self, "CallRuntime",
            handler="call_runtime.lambda_handler",
            code_path="app/fn_invoke_runtime",
            shared_layer=shared_layer.layer,
            timeout=Duration.minutes(5),
            description="Lambda client to invoke AgentCore Runtime",
            extra_env={"RUNTIME_ARN": runtime.runtime.agent_runtime_arn},
            extra_policies=[
                iam.PolicyStatement(
                    actions=[
                        "bedrock-agentcore:InvokeAgentRuntime",
                        "bedrock-agentcore:InvokeAgentRuntimeForUser",
                        "bedrock-agentcore:InvokeAgentRuntimeCommand",
                    ],
                    resources=["*"],
                )
            ],
        )
