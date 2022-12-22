hi


CDK
cd /source/cdk


Setup CDK
chmod +x ../../deployment/cdk-solution-helper/step2-setup-cdk-env.sh && ../../deployment/cdk-solution-helper/step2-setup-cdk-env.sh

Source environment
source ../../.venv/bin/activate

export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --output text --query Account)
Bootstrap pipeline
aws://$(aws sts get-caller-identity --output text --query Account)/eu-central-1

cdk bootstrap --tags map-migrated=d-server-002yz80gjzjqaa

1. Bootstrap:
export ACCOUNT_ID=$(aws sts get-caller-identity --output text --query Account)
cdk bootstrap --cloudformation-execution-policies arn\:aws\:iam::aws\:policy/AdministratorAccess aws://$ACCOUNT_ID/eu-central-1

2. Synthi
cdk synth SiemPipelineStack

3. Deploy 
cdk deploy SiemPipelineStack

