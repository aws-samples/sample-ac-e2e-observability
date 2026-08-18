"""CDK construct to register OAuth2 credentials in AgentCore Identity.

Uses a CloudFormation Custom Resource since there is no native CFN/CDK
resource for bedrock-agentcore-control OAuth2 credential providers yet.

Supports any OAuth2 vendor supported by the CreateOauth2CredentialProvider API:
  GoogleOauth2, GithubOauth2, SlackOauth2, SalesforceOauth2, MicrosoftOauth2,
  CustomOauth2, AtlassianOauth2, LinkedinOauth2, XOauth2, OktaOauth2,
  OneLoginOauth2, PingOneOauth2, FacebookOauth2, YandexOauth2, RedditOauth2,
  ZoomOauth2, TwitchOauth2, SpotifyOauth2, DropboxOauth2, NotionOauth2,
  HubspotOauth2, CyberArkOauth2, FusionAuthOauth2, Auth0Oauth2, CognitoOauth2

See: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/
     API_CreateOauth2CredentialProvider.html
"""

import json
from typing import Any

from aws_cdk import (
    Stack,
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    aws_iam as iam,
    aws_logs as logs,
    custom_resources as cr,
)
from aws_cdk.aws_lambda import Runtime, Code, Function
from constructs import Construct
from modules.ac_trace import AgentCoreTracing


# ---------------------------------------------------------------------------
# Inline Lambda that backs the CloudFormation Custom Resource.
# Receives vendor + provider config as opaque JSON so it works with any
# oauth2ProviderConfigInput union member.
# ---------------------------------------------------------------------------
_HANDLER_CODE = r"""
import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

client = boto3.client("bedrock-agentcore-control")


def handler(event, context):
    # CDK cr.Provider on_event handler.
    # Returns dict with PhysicalResourceId and Data (attributes for GetAtt).
    props = event["ResourceProperties"]
    request_type = event["RequestType"]
    provider_name = props["ProviderName"]
    vendor = props["Vendor"]
    config = json.loads(props["ProviderConfig"])

    if request_type in ("Create", "Update"):
        api_fn = (
            client.create_oauth2_credential_provider
            if request_type == "Create"
            else client.update_oauth2_credential_provider
        )
        resp = api_fn(
            name=provider_name,
            credentialProviderVendor=vendor,
            oauth2ProviderConfigInput=config,
        )
        logger.info("API response: %s", json.dumps(resp, default=str))
        secret_arn = (resp.get("clientSecretArn") or {}).get(
            "secretArn", "N/A"
        )
        return {
            "PhysicalResourceId": resp.get(
                "credentialProviderArn", provider_name
            ),
            "Data": {
                "CredentialProviderArn": resp.get(
                    "credentialProviderArn", "N/A"
                ),
                "SecretArn": secret_arn,
                "CallbackUrl": resp.get("callbackUrl", "N/A"),
                "Name": resp.get("name", provider_name),
            },
        }

    if request_type == "Delete":
        try:
            client.delete_oauth2_credential_provider(name=provider_name)
        except client.exceptions.ResourceNotFoundException:
            logger.info("Provider %s already deleted", provider_name)
        return {
            "PhysicalResourceId": event.get(
                "PhysicalResourceId", provider_name
            ),
        }

    raise ValueError(f"Unexpected RequestType: {request_type}")
"""


class AgentCoreIdentity(Construct):
    """Register an OAuth2 credential provider with AgentCore Identity (Token Vault).

    Works with any vendor supported by the bedrock-agentcore-control API.

    Example – Cognito::

        AgentCoreIdentity(self, "Identity",
            provider_name="my-cognito-provider",
            vendor="CustomOauth2",
            provider_config={
                "customOauth2ProviderConfig": {
                    "oauthDiscovery": {
                        "discoveryUrl": "https://cognito-idp.<region>.amazonaws.com/"
                            "<pool-id>/.well-known/openid-configuration"
                    },
                    "clientId": "<client-id>",
                    "clientSecret": "<client-secret>",
                }
            },
        )

    Example – GitHub::

        AgentCoreIdentity(self, "Identity",
            provider_name="my-github-provider",
            vendor="GithubOauth2",
            provider_config={
                "githubOauth2ProviderConfig": {
                    "clientId": "<github-client-id>",
                    "clientSecret": "<github-client-secret>",
                }
            },
        )
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vendor: str,
        provider_config: dict[str, Any],
        provider_name: str | None = None,
        **kwargs,
    ) -> None:
        """
        Args:
            vendor: One of the supported credentialProviderVendor values
                    (e.g. "CognitoOauth2", "CustomOauth2", "GithubOauth2").
            provider_config: The oauth2ProviderConfigInput dict matching the
                             vendor. This is a Union — only one key should be set.
            provider_name: Unique name for the provider (max 128 chars,
                           pattern [a-zA-Z0-9\\-_]+). Defaults to stack name based.
        """
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)
        self.name = provider_name or f"{stack.stack_name}-oauth2-provider"

        on_event_handler = Function(
            self, "Handler",
            runtime=Runtime.PYTHON_3_13,
            handler="index.handler",
            code=Code.from_inline(_HANDLER_CODE),
            timeout=Duration.minutes(2),
            log_group=logs.LogGroup(
                self, "HandlerLogs",
                retention=logs.RetentionDays.ONE_WEEK,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )

        on_event_handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:CreateOauth2CredentialProvider",
                    "bedrock-agentcore:UpdateOauth2CredentialProvider",
                    "bedrock-agentcore:DeleteOauth2CredentialProvider",
                    "bedrock-agentcore:GetOauth2CredentialProvider",
                    "bedrock-agentcore:CreateTokenVault",
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:UpdateSecret",
                ],
                resources=["*"],
            )
        )

        provider = cr.Provider(
            self, "Provider",
            on_event_handler=on_event_handler,
        )

        self._custom_resource = CustomResource(
            self, "OAuth2CredentialProvider",
            service_token=provider.service_token,
            removal_policy=RemovalPolicy.DESTROY,
            properties={
                "ProviderName": self.name,
                "Vendor": vendor,
                "ProviderConfig": json.dumps(provider_config),
            },
        )

        self.credential_provider_arn = self._custom_resource.get_att_string(
            "CredentialProviderArn"
        )
        self.secret_arn = self._custom_resource.get_att_string("SecretArn")
        self.callback_url = self._custom_resource.get_att_string("CallbackUrl")

        # Enable ID Provider tracing 
        AgentCoreTracing(
            self, "ID-Provider-Trace",
            resource_arn=self.credential_provider_arn
        )

        CfnOutput(
            self, "CredentialProviderName",
            description="AgentCore Identity OAuth2 Credential Provider name",
            value=self.name,
        )
        CfnOutput(
            self, "CredentialProviderArn",
            description="AgentCore Identity OAuth2 Credential Provider ARN",
            value=self.credential_provider_arn,
        )
        CfnOutput(
            self, "ClientSecretArn",
            description="AgentCore Identity OAuth2 Secrets Manager ARN for the client secret",
            value=self.secret_arn,
        )
