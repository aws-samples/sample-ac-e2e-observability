"""Reusable CDK construct for deploying an instrumented Lambda function.

Handles ADOT layer, Powertools layer, shared layer, OTEL env vars,
IAM policies, and CfnOutput. Each Lambda is configured via props.
"""

from pathlib import Path
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_lambda as _lambda,
    aws_iam as iam,
    Duration,
)
from constructs import Construct

_DEFAULT_BAGGAGE_ATTRIBUTES = "session.id,tenant.id,user.id"
_APP_ROOT = Path(__file__).resolve().parent / ".." / ".."


class InstrumentedLambda(Construct):
    """Deploy a Lambda function with ADOT OpenTelemetry instrumentation.

    Common configuration (layers, OTEL env vars, IAM policies) is handled
    automatically. Callers provide only what's unique to their Lambda.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        code_path: str,
        handler: str = "handler.lambda_handler",
        shared_layer: _lambda.ILayerVersion,
        description: str = "",
        timeout: Duration = Duration.seconds(30),
        memory_size: int = 128,
        architecture: _lambda.Architecture = _lambda.Architecture.ARM_64,
        enable_otel: bool = True,
        extra_env: dict[str, str] | None = None,
        extra_policies: list[iam.PolicyStatement] | None = None,
        extra_managed_policies: list[str] | None = None,
        **kwargs,
    ) -> None:
        """
        Args:
            code_path: Relative path from project root to the Lambda code directory.
            handler: Lambda handler string (default: handler.lambda_handler).
            shared_layer: The shared utilities Lambda layer.
            description: CfnOutput description.
            timeout: Lambda timeout (default: 30s).
            memory_size: Lambda memory in MB (default: 128).
            architecture: Lambda architecture (default: ARM_64).
            enable_otel: Whether to attach ADOT instrumentation (default: True).
            extra_env: Additional environment variables merged after OTEL vars.
            extra_policies: Additional inline IAM policy statements.
            extra_managed_policies: Additional AWS managed policy names.
        """
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)

        # --- Environment variables ---
        env_vars: dict[str, str] = {
            "POWERTOOLS_LOG_LEVEL": "INFO",
            "AGENT_OBSERVABILITY_ENABLED": "false",
        }
        if enable_otel:
            env_vars |= {
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
                "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "false",
                "OTEL_TRACES_SAMPLER": "always_on",
                "AGENT_OBSERVABILITY_ENABLED": "true",
                "AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT": "true",
                "OTEL_PROPAGATORS": "tracecontext,baggage,xray-lambda,xray",
                "OTEL_LOGS_EXPORTER": "none",
                "OTEL_METRICS_EXPORTER": "none",
                "OTEL_TRACES_EXPORTER": "otlp",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                "OTEL_PYTHON_DISTRO": "aws_distro",
                "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
                "OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS": _DEFAULT_BAGGAGE_ATTRIBUTES,
            }
            # Allow CDK context override for baggage keys
            ctx_baggage = self.node.try_get_context(
                "OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS"
            )
            if ctx_baggage:
                env_vars["OTEL_BAGGAGE_SPAN_ATTRIBUTE_KEYS"] = ctx_baggage

        # Merge caller-provided env vars (takes precedence)
        if extra_env:
            env_vars |= extra_env

        # --- Layers ---
        layers: list[_lambda.ILayerVersion] = [shared_layer]
        if enable_otel:
            layers.append(
                _lambda.LayerVersion.from_layer_version_arn(
                    self, "ADOT",
                    f"arn:aws:lambda:{stack.region}:615299751070"
                    ":layer:AWSOpenTelemetryDistroPython:29",
                )
            )
        layers.append(
            _lambda.LayerVersion.from_layer_version_arn(
                self, "Powertools",
                f"arn:aws:lambda:{stack.region}:017000801446"
                ":layer:AWSLambdaPowertoolsPythonV3-python313-arm64:33",
            )
        )

        # --- Lambda Function ---
        self.function = _lambda.Function(
            self, "Fn",
            runtime=_lambda.Runtime.PYTHON_3_13,
            architecture=architecture,
            code=_lambda.Code.from_asset(str(_APP_ROOT / code_path)),
            handler=handler,
            timeout=timeout,
            memory_size=memory_size,
            tracing=_lambda.Tracing.DISABLED,
            environment=env_vars,
            layers=layers,
        )

        # --- IAM policies ---
        if enable_otel:
            self.function.role.add_managed_policy(
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "CloudWatchLambdaApplicationSignalsExecutionRolePolicy"
                )
            )
            self.function.role.add_managed_policy(
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AWSXRayDaemonWriteAccess"
                )
            )
        if extra_managed_policies:
            for policy_name in extra_managed_policies:
                self.function.role.add_managed_policy(
                    iam.ManagedPolicy.from_aws_managed_policy_name(policy_name)
                )
        if extra_policies:
            for statement in extra_policies:
                self.function.add_to_role_policy(statement)

        # --- Output ---
        CfnOutput(
            self, "FnArn",
            description=description or f"Lambda ARN for {construct_id}",
            value=self.function.function_arn,
        )
