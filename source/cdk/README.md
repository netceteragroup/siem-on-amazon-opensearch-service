hi



# Deploy SIEM from Workmachine

Point to app.py in /source/cdk/cdk.json

Execute:
$./deployment/deploySiem.sh

# Manual changes

## Gihub Connection
The Github Connection in AWS Logging Account is currently bound to nca-ggi repo holding
https://docs.aws.amazon.com/codepipeline/latest/userguide/connections-github.html

This should be changed so that it has access on the nca organization repository instead. This requires organization owner credentials.


## Problem 1:  SiemPipelineStack-SiemPipelineStackPipelineBuildSy
Manual update of the role SiemPipelineStack-SiemPipelineStackPipelineBuildSy to allow action iam:* on the ressource   arn:aws:iam::755880545038:role/aws-service-role/opensearchservice.amazonaws.com/
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the ListRoles operation: User: arn:aws:sts::755880545038:assumed-role/SiemPipelineStack-SiemPipelineStackPipelineBuildSy-IV71O0NP0NCM/AWSCodeBuild-a8750589-e93c-4363-81ad-8686196d941f is not authorized to perform: iam:ListRoles on resource: arn:aws:iam::755880545038:role/aws-service-role/opensearchservice.amazonaws.com/ because no identity-based policy allows the iam:ListRoles action