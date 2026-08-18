# CDK command reference
Basic CDK command reference to get started.

### Set up CDK

```bash
npm install -g aws-cdk
cdk cli-telemetry --disable
export CDK_DOCKER=finch  # Optional: use Finch instead of Docker
```

### Bootstrap CDK

```bash
uv run cdk bootstrap aws://<account>/<region>
```

### Common CDK commands

```bash
uv run cdk ls          # List all stacks
uv run cdk synth       # Emit the CloudFormation template
uv run cdk deploy      # Deploy the stack
uv run cdk diff        # Compare deployed state with local
uv run cdk docs        # Open CDK documentation
```
