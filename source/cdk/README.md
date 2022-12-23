hi

# Prerequisites
Setup Github Connection in AWS Logging Account
https://docs.aws.amazon.com/codepipeline/latest/userguide/connections-github.html

# Deploy SIEM from Workmachine

Point to app.py in /source/cdk/cdk.json

Execute:
$./deployment/deploySiem.sh




CDK
cd /source/cdk


Setup CDK
chmod +x ../../deployment/cdk-solution-helper/step2-setup-cdk-env.sh && ../../deployment/cdk-solution-helper/step2-setup-cdk-env.sh

Source environment
source ../../.venv/bin/activate

export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --output text --query Account)


