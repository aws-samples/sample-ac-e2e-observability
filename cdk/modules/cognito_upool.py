"""CDK construct to create Cognito user pool and register agentcore gateway"""

import os
import re
import hashlib
from aws_cdk import (
    Stack,
    aws_cognito as cognito,
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from constructs import Construct

# For backward compatibility with legacy less portable unique user pool naming
LEGACY_UPOOL_NAME = os.getenv("LEGACY_UPOOL_NAME", None)


class CognitoUserPool(Construct):
    """Create Agentcore Gateway sample user pool and register resource"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)
        # Create Cognito User Pool
        user_pool = cognito.UserPool(
            self, "UserPool",
            user_pool_name=f"{stack.stack_name}-upool",
            # Sign-in configuration
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=True
            ),
            # Self sign-up configuration
            self_sign_up_enabled=False,
            # Auto verify email addresses
            auto_verify=cognito.AutoVerifiedAttrs(
                email=True
            ),
            # MFA configuration - DISABLED
            mfa=cognito.Mfa.OFF,
            # User verification
            user_verification=cognito.UserVerificationConfig(
                email_subject="Verify your email for our app!",
                email_body="Thanks for signing up! Your verification code is {####}",
                email_style=cognito.VerificationEmailStyle.CODE,
                sms_message="Thanks for signing up! Your verification code is {####}"
            ),
            # Standard attributes
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                ),
                given_name=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                ),
                family_name=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                )
            ),
            # Password policy
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True
            ),
            # Account recovery
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            # Removal policy for development (change for production)
            removal_policy=RemovalPolicy.DESTROY
        )

        # Create Resource Server with Custom Scopes
        gw_read_scope = cognito.ResourceServerScope(
            scope_name="gateway:read",
            scope_description="Read access to Agentcore Gateway"
        )
        gw_write_scope = cognito.ResourceServerScope(
            scope_name="gateway:write",
            scope_description="Write access to Agentcore Gateway"
        )
        resource_server = cognito.UserPoolResourceServer(
            self, "GWResourceServer",
            user_pool=user_pool,
            identifier=f"{stack.stack_name}-acgw-rs",
            user_pool_resource_server_name=f"{stack.stack_name}-acgw-rs",
            scopes=[gw_read_scope, gw_write_scope]
        )

        # Create Machine-to-Machine (M2M) Client
        m2m_client = cognito.UserPoolClient(
            self, "M2MClient",
            user_pool=user_pool,
            user_pool_client_name=f"{stack.stack_name}-m2m-client",
            # Authentication flows for M2M
            auth_flows=cognito.AuthFlow(
                custom=True,
                # user_password=True,  # Required for refresh token flow
                # user_srp=True       # Required for refresh token flow
            ),
            # OAuth settings for M2M
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    client_credentials=True,  # Client Credentials Grant for M2M
                    # authorization_code_grant=True  # Added for refresh token support
                ),
                scopes=[
                    # Custom scopes for M2M access
                    cognito.OAuthScope.resource_server(resource_server, gw_read_scope),
                    cognito.OAuthScope.resource_server(resource_server, gw_write_scope)
                ],
                # # Add callback URLs for M2M client (required for authorization code flow)
                # callback_urls=["https://localhost:3000/m2m-callback"]
            ),
            # Token validity for M2M
            access_token_validity=Duration.hours(24),  # Longer validity for M2M
            refresh_token_validity=Duration.days(90),  # Long-lived refresh tokens for M2M
            # Generate secret (required for M2M)
            generate_secret=True,
            # Prevent user existence errors
            prevent_user_existence_errors=True,
            # Enable refresh token rotation for better security
            enable_token_revocation=True
        )

        # Create User Pool Domain for hosted UI
        # Domain prefix must be globally unique across all AWS accounts
        # Only lowercase alphanumeric and hyphens are allowed
        # Use Fn.Select + Fn.Split on account ID to avoid unresolved tokens
        addr_hash = hashlib.sha256(self.node.addr.encode()).hexdigest()[:12]
        sanitized_name = re.sub(r'[^a-z0-9-]', '', stack.stack_name.lower())
        domain_prefix = f"{sanitized_name}-{addr_hash}"
        if LEGACY_UPOOL_NAME:
            domain_prefix = (
                f"{stack.stack_name.replace('_', '').lower()}"
                f"-{self.node.addr[:8].lower()}"
            )

        user_pool_domain = cognito.UserPoolDomain(
            self, "UserPoolDomain",
            user_pool=user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=domain_prefix
            )
        )

        # Create User Pool Client
        # user_pool_client = cognito.UserPoolClient(
        #     self, "UserPoolClient",
        #     user_pool=user_pool,
        #     user_pool_client_name="my-app-client",
        #     # Authentication flows
        #     auth_flows=cognito.AuthFlow(
        #         user_password=True,
        #         user_srp=True,
        #         custom=True,
        #         admin_user_password=True
        #     ),
        #     # OAuth settings
        #     o_auth=cognito.OAuthSettings(
        #         flows=cognito.OAuthFlows(
        #             authorization_code_grant=True,
        #             implicit_code_grant=True
        #         ),
        #         scopes=[
        #             cognito.OAuthScope.EMAIL,
        #             cognito.OAuthScope.OPENID,
        #             cognito.OAuthScope.PROFILE
        #         ],
        #         callback_urls=["https://localhost:3000/callback"],
        #         logout_urls=["https://localhost:3000/logout"]
        #     ),
        #     # Token validity
        #     access_token_validity=Duration.hours(1),
        #     id_token_validity=Duration.hours(1),
        #     refresh_token_validity=Duration.days(30),
        #     # Prevent user existence errors
        #     prevent_user_existence_errors=True,
        #     # Generate secret (set to False for mobile/SPA apps)
        #     generate_secret=False
        # )

        self.user_pool = user_pool
        self.user_pool_client = m2m_client

        # Outputs
        CfnOutput(
            self, "UserPoolId",
            description="Cognito User Pool ID",
            value=user_pool.user_pool_id
        )

        CfnOutput(
            self, "UserPoolArn",
            description="Cognito User Pool ARN",
            value=user_pool.user_pool_arn
        )

        CfnOutput(
            self, "UserPoolDomainUrl",
            description="Cognito Hosted UI URL",
            value=f"https://{user_pool_domain.domain_name}.auth.{stack.region}.amazoncognito.com",
        )

        CfnOutput(
            self, "M2MClientId",
            description="Cognito M2M Client ID",
            value=m2m_client.user_pool_client_id
        )

        # CfnOutput(
        #     self, "M2MClientSecret",
        #     description="Cognito M2M Client Secret",
        #     value=m2m_client.user_pool_client_secret.unsafe_unwrap()
        # )

        CfnOutput(
            self, "ResourceServerIdentifier",
            description="Agentcore Gateway Resource Server Identifier",
            value=resource_server.user_pool_resource_server_id
        )

        CfnOutput(
            self, "DiscoveryUrl",
            description="Cognito Hosted UI URL",
            value=(
                f"https://cognito-idp.{stack.region}.amazonaws.com/"
                f"{user_pool.user_pool_id}/.well-known/openid-configuration"
            )
        )

        CfnOutput(
            self, "TokenEndpoint",
            description="OAuth2 Token Endpoint for M2M",
            value=(
                f"https://{user_pool_domain.domain_name}.auth.{stack.region}"
                ".amazoncognito.com/oauth2/token"
            )
        )
