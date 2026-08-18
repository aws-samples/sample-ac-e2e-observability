"""CDK construct to create Agentcore Runtime"""

from pathlib import Path
from aws_cdk import (
    Stack,
    aws_bedrockagentcore as _agentcore,
    aws_bedrock_alpha as _bedrock,
    aws_iam as iam,
    CfnOutput,
    Duration,
)
from constructs import Construct
from modules.ac_trace import AgentCoreTracing
from modules.ac_vendedlogs import AgentCoreVendedLog

_DEFAULT_BAGGAGE_ATTRIBUTES = "session.id,tenant.id,user.id"
_AGENT_DIR = str(
    Path(__file__).resolve().parent / ".." / ".." / "app" / "agent"
)


class AgentCoreRuntime(Construct):
    """Create AgentCore Runtime"""

    def __init__(
            self, scope: Construct, construct_id: str,
            gateway_url: str,
            gateway_oauth2_provider_name: str,
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

        model = _bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_SONNET_4_5_V1_0
        inference_profile = _bedrock.CrossRegionInferenceProfile.from_config(
            geo_region=_bedrock.CrossRegionInferenceProfileRegion.US,
            model=model
        )
        agent_runtime_artifact = _agentcore.AgentRuntimeArtifact.from_asset(_AGENT_DIR)
        env_vars = {
            "BEDROCK_MODEL_ID": inference_profile.inference_profile_id,
            "AWS_REGION": stack.region,
            "AGENTCORE_GW_URL": gateway_url,
            "ACI_GW_OAUTH2_PROVIDER_NAME": gateway_oauth2_provider_name,
            "ACI_GW_OAUTH2_SCOPES": (
                "ac-oauth-demo-acgw-rs/gateway:read,"
                "ac-oauth-demo-acgw-rs/gateway:write"
            ),

            # OTEL Configurations
            "AGENT_OBSERVABILITY_ENABLED": "true",

            "OTEL_PROPAGATORS": "tracecontext,baggage,xray",
            "OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS": _DEFAULT_BAGGAGE_ATTRIBUTES,

            # "OTEL_PYTHON_EXCLUDED_URLS": "169.254.169.254,/ping,/health,/mcp",
            "OTEL_PYTHON_EXCLUDED_URLS": "169.254.169.254,/ping,/health",
            # "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "urllib3,requests,botocore,aiohttp-client,httpx",
            "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": "urllib3,requests,aiohttp-client,httpx",
        }
        if otel_semconv_enabled:
            env_vars["OTEL_SEMCONV_STABILITY_OPT_IN"] = (
                "gen_ai_latest_experimental,gen_ai_span_attributes_only"
            )
        if genai_content_opt_out:
            env_vars["AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT"] = "true"
        if env_baggage_keys:
            env_vars["OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS"] = env_baggage_keys

        self.runtime = _agentcore.Runtime(
            self, "AgentRuntime",
            runtime_name=f"{stack.stack_name}-rt".replace("-", "_"),
            agent_runtime_artifact=agent_runtime_artifact,
            environment_variables=env_vars,
        )
        model.grant_invoke(self.runtime)
        inference_profile.grant_invoke(self.runtime)

        # Grant runtime access to AgentCore Identity OAuth2 tokens
        self.runtime.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                sid="GetResourceOauth2Token",
                actions=["bedrock-agentcore:GetResourceOauth2Token"],
                resources=["*"],
            )
        )
        self.runtime.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                sid="SecretManager",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    "arn:aws:secretsmanager:*:*:secret:bedrock-agentcore*"
                ],
            )
        )

        # Enable Runtime tracing and application logging
        AgentCoreTracing(
            self, "RT-Trace",
            resource_arn=self.runtime.agent_runtime_arn
        )
        AgentCoreVendedLog(
            self, "RT-AppLogs",
            resource_type="runtime",
            resource_arn=self.runtime.agent_runtime_arn
        )

        self.evaluation = _agentcore.OnlineEvaluationConfig(
            self, "OnlineEval",
            online_evaluation_config_name=f"{stack.stack_name}-rt-eval".replace("-", "_"),
            evaluators=[
                # Session level
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.GOAL_SUCCESS_RATE),
                # Trace level - quality
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.HELPFULNESS),
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.CORRECTNESS),
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.RESPONSE_RELEVANCE),
                # _agentcore.EvaluatorReference.builtin(_agentcore.BuiltinEvaluator.COHERENCE),
                # Trace level - safety
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.HARMFULNESS),
                # _agentcore.EvaluatorReference.builtin(_agentcore.BuiltinEvaluator.STEREOTYPING),
                # Tool call level
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.TOOL_SELECTION_ACCURACY),
                _agentcore.EvaluatorSelector.builtin(_agentcore.BuiltinEvaluator.TOOL_PARAMETER_ACCURACY)
            ],
            data_source=_agentcore.DataSourceConfig.from_agent_runtime_endpoint(self.runtime),
            # data_source=_agentcore.DataSourceConfig.from_cloud_watch_logs(
            #     log_group_names=[f"/aws/bedrock-agentcore/runtimes/{self.runtime.agent_runtime_id}-DEFAULT"],
            #     service_names=[f"{self.runtime.agent_runtime_id}.DEFAULT"]
            # ),
            sampling_percentage=100,
            session_timeout=Duration.minutes(1),
        )
        CfnOutput(
            self, "ac_runtime_id",
            description="Agentcore Runtime ID",
            value=self.runtime.agent_runtime_id
        )
        CfnOutput(
            self, "ac_runtime_name",
            description="Agentcore Runtime name",
            value=self.runtime.agent_runtime_name
        )
        CfnOutput(
            self, "ac_evaluation_id",
            description="Agentcore Online Evaluation ID",
            value=self.evaluation.online_evaluation_config_id
        )
