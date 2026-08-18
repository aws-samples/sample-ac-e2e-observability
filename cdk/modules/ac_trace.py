"""CDK construct to enable observability for Bedrock AgentCore Services.

Sets up CloudWatch Logs delivery (APPLICATION_LOGS) and X-Ray traces delivery
using the AWS::Logs::DeliverySource / DeliveryDestination / Delivery L1 constructs.
"""

from aws_cdk import (
    Fn,
    aws_logs as logs,
)
from constructs import Construct


class AgentCoreTracing(Construct):
    """Enable vended log and trace delivery for an AgentCore resource.

    Creates:
      - CloudWatch Log Group for application logs
      - DeliverySource + DeliveryDestination + Delivery for TRACES → X-Ray
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        resource_id: str | None = None,
        resource_arn: str,
        **kwargs,
    ) -> None:
        """
        Args:
            resource_id: The AgentCore resource ID. If not provided,
                         derived from the last segment of resource_arn.
            resource_arn: The full ARN of the AgentCore resource.
        """
        super().__init__(scope, construct_id, **kwargs)
        # ARN format: arn:aws:bedrock-agentcore:<region>:<account>:<type>/<id>
        # Fn.select/Fn.split works at deploy time on token values
        resolved_id = Fn.select(1, Fn.split("/", resource_arn))
        resource_id = resource_id or resolved_id

        traces_source = logs.CfnDeliverySource(
            self, "TracesSource",
            name=f"{resource_id}-traces-source",
            log_type="TRACES",
            resource_arn=resource_arn,
        )

        traces_destination = logs.CfnDeliveryDestination(
            self, "TracesDestination",
            name=f"{resource_id}-traces-destination",
            delivery_destination_type="XRAY",
        )

        traces_delivery = logs.CfnDelivery(
            self, "TracesDelivery",
            delivery_source_name=traces_source.name,
            delivery_destination_arn=traces_destination.attr_arn,
        )
        traces_delivery.add_dependency(traces_source)
        traces_delivery.add_dependency(traces_destination)
