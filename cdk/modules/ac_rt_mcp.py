"""CDK construct to create Agentcore Runtime MCP"""

from pathlib import Path
from aws_cdk import (
    Stack,
    aws_bedrockagentcore as _agentcore,
    CfnOutput,
)
from constructs import Construct
from modules.cognito_upool import CognitoUserPool
from modules.ac_trace import AgentCoreTracing
from modules.ac_vendedlogs import AgentCoreVendedLog

_DEFAULT_BAGGAGE_ATTRIBUTES = "session.id,tenant.id,user.id"

_MCP_DIR = str(
    Path(__file__).resolve().parent / ".." / ".." / "app" / "mcp"
)


class AgentCoreRuntimeMCP(Construct):
    """Create AgentCore Runtime MCP"""

    def __init__(
            self, scope: Construct, construct_id: str,
            upool: CognitoUserPool,
            **kwargs
        ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)
        otel_semconv_enabled = self.node.try_get_context(
            "OTEL_SEMCONV_STABILITY_OPT_IN"
        )
        genai_content_opt_out = self.node.try_get_context(
            "AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT"
        )
        env_baggage_keys = self.node.try_get_context(
            "OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS"
        )

        agent_runtime_artifact = _agentcore.AgentRuntimeArtifact.from_asset(_MCP_DIR)
        env_vars = {
            "AWS_REGION": stack.region,

            # OTEL Configurations
            "AGENT_OBSERVABILITY_ENABLED": "true",
            "LOG_LEVEL": "INFO",

            "OTEL_PROPAGATORS": "tracecontext,baggage,xray",
            "OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS": _DEFAULT_BAGGAGE_ATTRIBUTES,
            # "OTEL_PYTHON_EXCLUDED_URLS": "169.254.169.254,/ping,/health,/mcp",
            "OTEL_PYTHON_EXCLUDED_URLS": "169.254.169.254,/ping,/health",
            # "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "urllib3,requests,botocore,aiohttp-client,httpx",
            # "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "urllib3,requests,aiohttp-client,httpx",
        }
        if otel_semconv_enabled:
            env_vars["OTEL_SEMCONV_STABILITY_OPT_IN"] = (
                "gen_ai_latest_experimental,gen_ai_span_attributes_only"
            )
        if genai_content_opt_out:
            env_vars["AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT"] = "true"
        if env_baggage_keys:
            env_vars["OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS"] = env_baggage_keys

        self.mcp_runtime = _agentcore.Runtime(
            self, "AgentRuntimeMCP",
            runtime_name=f"{stack.stack_name}-rt-mcp".replace("-", "_"),
            agent_runtime_artifact=agent_runtime_artifact,
            environment_variables=env_vars,
            protocol_configuration=_agentcore.ProtocolType.MCP,
            # JWT (Cognito) inbound auth so the gateway can present an OAuth
            # bearer token instead of SigV4 (which requires a user-id header).
            authorizer_configuration=(
                _agentcore.RuntimeAuthorizerConfiguration.using_cognito(
                    user_pool=upool.user_pool,
                    user_pool_clients=[upool.user_pool_client],
                )
            ),
        )

        # Enable Runtime tracing and application logging
        AgentCoreTracing(
            self, "RT-MCP-Trace",
            resource_arn=self.mcp_runtime.agent_runtime_arn
        )
        AgentCoreVendedLog(
            self, "RT-MCP-AppLogs",
            resource_type="runtime",
            resource_arn=self.mcp_runtime.agent_runtime_arn
        )
        CfnOutput(
            self, "ac_runtime_mcp_id",
            description="Agentcore Runtime MCP ID",
            value=self.mcp_runtime.agent_runtime_id
        )
        CfnOutput(
            self, "ac_runtime_mcp_arn",
            description="Agentcore Runtime MCP ARN",
            value=self.mcp_runtime.agent_runtime_arn
        )
        CfnOutput(
            self, "ac_runtime_mcp_name",
            description="Agentcore Runtime MCP name",
            value=self.mcp_runtime.agent_runtime_name
        )
