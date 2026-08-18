"""CDK construct to retrieve Gateway Workload Identity ARN via custom resource"""

from aws_cdk import (
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    aws_iam as iam,
    aws_logs as logs,
    custom_resources as cr,
)
from aws_cdk.aws_lambda import Runtime, Code, Function
from aws_cdk.aws_bedrockagentcore import IGateway
from constructs import Construct


_GET_GW_CODE = (
    "import boto3\n"
    "client = boto3.client('bedrock-agentcore-control')\n"
    "def handler(event, context):\n"
    "    rt = event['RequestType']\n"
    "    gw_id = event['ResourceProperties']['GatewayId']\n"
    "    if rt in ('Create', 'Update'):\n"
    "        resp = client.get_gateway(gatewayIdentifier=gw_id)\n"
    "        wid = resp.get('workloadIdentityDetails', {})\n"
    "        return {\n"
    "            'PhysicalResourceId': gw_id,\n"
    "            'Data': {\n"
    "                'WorkloadIdentityArn': wid.get('workloadIdentityArn', 'N/A'),\n"
    "            },\n"
    "        }\n"
    "    return {'PhysicalResourceId': gw_id}\n"
)


class GatewayWorkloadIdentity(Construct):
    """Retrieve the Workload Identity ARN from a Gateway via GetGateway API.

    The CloudFormation schema for AWS::BedrockAgentCore::Gateway does not
    expose WorkloadIdentityDetails as a readonly attribute, so a custom
    resource Lambda is used to call the GetGateway API after creation.
    """

    def __init__(
            self, scope: Construct, construct_id: str,
            gateway: IGateway,
            **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        get_gw_handler = Function(
            self, "Handler",
            runtime=Runtime.PYTHON_3_13,
            handler="index.handler",
            code=Code.from_inline(_GET_GW_CODE),
            timeout=Duration.seconds(30),
            log_group=logs.LogGroup(
                self, "Logs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        get_gw_handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:GetGateway"],
                resources=["*"],
            )
        )

        provider = cr.Provider(
            self, "Provider",
            on_event_handler=get_gw_handler,
        )

        custom_resource = CustomResource(
            self, "CR",
            service_token=provider.service_token,
            properties={"GatewayId": gateway.gateway_id},
        )
        custom_resource.node.add_dependency(gateway)

        self.workload_identity_arn = custom_resource.get_att_string(
            "WorkloadIdentityArn"
        )

        CfnOutput(
            self, "workload_identity_arn",
            description="Gateway Workload Identity ARN",
            value=self.workload_identity_arn,
        )
