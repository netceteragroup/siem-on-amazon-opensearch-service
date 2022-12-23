#!/bin/sh

export CDK_DEFAULT_ACCOUNT=755880545038
export AWS_DEFAULT_REGION=eu-central-1
pwd

cd cdk-solution-helper/
chmod +x ./step1-build-lambda-pkg.sh && ./step1-build-lambda-pkg.sh
chmod +x ./step2-setup-cdk-env.sh && ./step2-setup-cdk-env.sh
source ~/.bashrc
cd ../../
source .venv/bin/activate
cd source/cdk
cdk bootstrap
cdk context  --j
cdk deploy --no-rollback
