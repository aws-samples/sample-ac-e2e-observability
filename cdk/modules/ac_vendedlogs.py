"""CDK construct to enable observability for Bedrock AgentCore Services.

Sets up CloudWatch Logs delivery (APPLICATION_LOGS) and X-Ray traces delivery
using the AWS::Logs::DeliverySource / DeliveryDestination / Delivery L1 constructs.
"""

from aws_cdk import (
    Fn,
    RemovalPolicy,
    aws_logs as logs,
)
from constructs import Construct


class AgentCoreVendedLog(Construct):
    """Enable vended log and trace delivery for an AgentCore resource.

    Creates:
      - CloudWatch Log Group for application logs
      - DeliverySource + DeliveryDestination + Delivery for APPLICATION_LOGS → CWL
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        resource_type: str,
        resource_arn: str,
        resource_id: str | None = None,
        log_type: str = "APPLICATION_LOGS",
        log_retention: logs.RetentionDays = logs.RetentionDays.TWO_YEARS,
        **kwargs,
    ) -> None:
        """
        Args:
            resource_id: The AgentCore resource ID. If not provided,
                         derived from the last segment of resource_arn.
            resource_arn: The full ARN of the AgentCore resource.
            log_retention: Log retention period (default TWO_YEARS).
        """
        super().__init__(scope, construct_id, **kwargs)
        # ARN format: arn:aws:bedrock-agentcore:<region>:<account>:<type>/<id>
        resolved_id = Fn.select(1, Fn.split("/", resource_arn))
        resource_id = resource_id or resolved_id

        # --- CloudWatch Log Group for vended logs ---
        self.log_group = logs.LogGroup(
            self, "LogGroup",
            log_group_name=f"/aws/vendedlogs/bedrock-agentcore/{resource_type}/{log_type}/{resource_id}",
            retention=log_retention,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Application Logs delivery pipeline ---
        logs_source = logs.CfnDeliverySource(
            self, "LogsSource",
            name=f"{resource_id}-logs-source",
            log_type=log_type,
            resource_arn=resource_arn,
        )

        logs_destination = logs.CfnDeliveryDestination(
            self, "LogsDestination",
            name=f"{resource_id}-logs-destination",
            delivery_destination_type="CWL",
            destination_resource_arn=self.log_group.log_group_arn,
        )

        logs_delivery = logs.CfnDelivery(
            self, "LogsDelivery",
            delivery_source_name=logs_source.name,
            delivery_destination_arn=logs_destination.attr_arn,
        )
        logs_delivery.add_dependency(logs_source)
        logs_delivery.add_dependency(logs_destination)
