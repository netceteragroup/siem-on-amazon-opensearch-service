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
Attached AdminAccess policy 
