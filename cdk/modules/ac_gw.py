"""CDK construct to create Agentcore Gateway"""

from aws_cdk import (
    Stack,
    CfnOutput,
    aws_bedrockagentcore as _agentcore,
    aws_bedrock_agentcore_alpha as _agentcore_alpha,
    aws_iam as iam,
)
from aws_cdk.aws_lambda import IFunction
from constructs import Construct
from modules.cognito_upool import CognitoUserPool
from modules.ac_trace import AgentCoreTracing
from modules.ac_vendedlogs import AgentCoreVendedLog
from modules.ac_gw_workload_id import GatewayWorkloadIdentity


class AgentCoreGateway(Construct):
    """Create AgentCore Gateway"""

    def __init__(
            self, scope: Construct, construct_id: str,
            upool: CognitoUserPool,
            request_interceptor_fn: IFunction = None,
            response_interceptor_fn: IFunction = None,
            **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)
        interceptor_configurations = []
        if request_interceptor_fn:
            interceptor_configurations.append(
                _agentcore.LambdaInterceptor.for_request(
                    request_interceptor_fn,
                    pass_request_headers=True
                )
            )
        if response_interceptor_fn:
            interceptor_configurations.append(
                _agentcore.LambdaInterceptor.for_response(
                    response_interceptor_fn,
                    pass_request_headers=True
                ),
            )
        self.gateway = _agentcore.Gateway(
            self, "Gateway",
            gateway_name=f"{stack.stack_name}-gw",
            authorizer_configuration=_agentcore.GatewayAuthorizer.using_cognito(
                user_pool=upool.user_pool,
                allowed_clients=[upool.user_pool_client],
            ),
            interceptor_configurations=interceptor_configurations
        )
        # Enable GW tracing and application logging
        AgentCoreTracing(
            self, "GW-Trace",
            resource_arn=self.gateway.gateway_arn
        )
        AgentCoreVendedLog(
            self, "GW-AppLogs",
            resource_type="gateway",
            resource_arn=self.gateway.gateway_arn
        )

        # Add policy engine and policy
        policy_engine = _agentcore_alpha.PolicyEngine(
            self, "PE",
            policy_engine_name=f"{stack.stack_name}-policy".replace("-", "_")
        )
        cfn_gateway = self.gateway.node.default_child
        cfn_gateway.policy_engine_configuration = _agentcore.CfnGateway.GatewayPolicyEngineConfigurationProperty(
            arn=policy_engine.policy_engine_arn,
            mode=_agentcore_alpha.PolicyEngineMode.LOG_ONLY.value,
        )
        _agentcore_alpha.Policy(
            self, "AllowAllPolicy",
            policy_engine=policy_engine,
            policy_name="allow_all",
            statement=(
                _agentcore_alpha
                .PolicyStatement.permit()
                .for_all_principals()
                .on_all_actions()
                .on_resource("AgentCore::Gateway", self.gateway.gateway_arn)
            ),
            description="Allow all actions on specific gateway (development only)",
            validation_mode=_agentcore_alpha.PolicyValidationMode.IGNORE_ALL_FINDINGS
        )
        # Grant evaluate permissions to the gateway role
        self.gateway.role.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:GetPolicyEngine"],
            resources=[policy_engine.policy_engine_arn]
        ))
        self.gateway.role.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:AuthorizeAction", "bedrock-agentcore:PartiallyAuthorizeActions"],
            resources=[policy_engine.policy_engine_arn, self.gateway.gateway_arn]
        ))
        # Grant gateway role permission to get workload access tokens
        self.gateway.role.add_to_principal_policy(iam.PolicyStatement(
            actions=["bedrock-agentcore:GetWorkloadAccessToken"],
            resources=[
                f"arn:aws:bedrock-agentcore:{stack.region}:{stack.account}"
                f":workload-identity-directory/default",
                f"arn:aws:bedrock-agentcore:{stack.region}:{stack.account}"
                f":workload-identity-directory/default/workload-identity/*",
            ],
        ))

        CfnOutput(
            self, "ac_gateway_id",
            description="Agentcore Gateway ID",
            value=self.gateway.gateway_id
        )
        CfnOutput(
            self, "ac_gateway_url",
            description="Agentcore Gateway URL",
            value=self.gateway.gateway_url
        )

        # Retrieve workload identity ARN (not exposed by L2 or CloudFormation)
        gw_identity = GatewayWorkloadIdentity(
            self, "GW-Identity",
            gateway=self.gateway,
        )
        self.workload_identity_arn = gw_identity.workload_identity_arn

        # Enable GW-Identity tracing and application logging
        AgentCoreTracing(
            self, "GW-ID-Trace",
            resource_arn=self.workload_identity_arn,
            resource_id=f"{stack.stack_name}-gw-identity",
        )
        AgentCoreVendedLog(
            self, "GW-ID-AppLogs",
            resource_type="workload-identity-directory",
            resource_arn=self.workload_identity_arn,
            resource_id=f"{stack.stack_name}-gw-identity",
        )
