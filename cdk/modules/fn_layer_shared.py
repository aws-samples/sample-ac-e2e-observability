"""CDK construct to deploy shared Lambda layer"""

from pathlib import Path
from aws_cdk import (
    aws_lambda as _lambda,
)
from constructs import Construct

_LAYER_DIR = str(Path(__file__).resolve().parent / ".." / ".." / "app" / "fn_shared")


class FnSharedLayer(Construct):
    """Deploys a shared Lambda layer containing custom_span utilities."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.layer = _lambda.LayerVersion(
            self, "SharedUtils",
            code=_lambda.Code.from_asset(_LAYER_DIR),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_13],
            description="Shared utilities: custom_span (OTel helpers)",
        )
