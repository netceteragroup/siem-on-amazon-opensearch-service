#!/bin/sh

export CDK_DEFAULT_ACCOUNT=755880545038
export AWS_DEFAULT_REGION=eu-central-1
pwd

cd cdk-solution-helper/

#chmod +x ./step1-build-lambda-pkg.sh && ./step1-build-lambda-pkg.sh
#chmod +x ./step2-setup-cdk-env.sh && ./step2-setup-cdk-env.sh
source ~/.bashrc
cd ../../
source .venv/bin/activate
cd source/cdk
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --output text --query Account)
export ACCOUNT_ID=$(aws sts get-caller-identity --output text --query Account)
cdk bootstrap --tags map-migrated=d-server-002yz80gjzjqaa --cloudformation-execution-policies arn\:aws\:iam::aws\:policy/AdministratorAccess aws://$ACCOUNT_ID/eu-central-1
cdk context --j
cdk synth SiemPipelineStack
cdk deploy SiemPipelineStack --no-rollback
