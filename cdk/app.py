#!/usr/bin/env python3
"""Build and deploy CDK application stack"""

import os

import aws_cdk as cdk

from stacks.ac_obs_demo_stack import ACObsDemoStack

# CDK context keys that can be set via environment variables
# (e.g. from .env.cdk.mon when using `uv run --env-file .env.cdk.mon cdk deploy`)
_ENV_CONTEXT_KEYS = [
    "OTEL_SEMCONV_STABILITY_OPT_IN",
    "AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT",
    "ENABLE_GW_REQUEST_INTERCEPTOR",
    "ENABLE_GW_RESPONSE_INTERCEPTOR",
]

app = cdk.App()

# Merge environment variables into CDK context (CLI -c flags take precedence)
for key in _ENV_CONTEXT_KEYS:
    if app.node.try_get_context(key) is None and os.environ.get(key):
        app.node.set_context(key, os.environ[key])

ACObsDemoStack(
    app, "ac-oauth-demo",
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.

    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.

    # env=cdk.Environment(
    #     account=os.getenv('CDK_DEFAULT_ACCOUNT'),
    #     region=os.getenv('CDK_DEFAULT_REGION')
    # ),

    # Uncomment the next line if you know exactly what Account and Region you
    # want to deploy the stack to. */

    # env=cdk.Environment(account='123456789012', region='us-east-1'),

    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
)

app.synth()
