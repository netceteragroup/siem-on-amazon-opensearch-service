# Deploy SIEM over AWS Pipeline

## Local Installation Requirements

Setup CDK
$ chmod +x ./cdk-solution-helper/step2-setup-cdk-env.sh && ./cdk-solution-helper/step2-setup-cdk-env.sh

Build Artifacts (Lambda) over helper script
$ ./deployment/buildLambdas.sh

Push artifacts to github

## Bootstrap 

1. The pipeline source can be adapted in /source/cdk/mysiem/siem_pipeline_stack.py
2. Push all changes to Github
3. Bootstrap Pipeline to AWS Logging Account
$./deployment/deployPipeline.sh
4. Manually trigger pipeline

# Manual changes to the Pipeline Setup

## Gihub Connection
The Github Connection in AWS Logging Account is bound to netceteragroup repository https://github.com/netceteragroup/siem-on-amazon-opensearch-service

Setup:
https://docs.aws.amazon.com/codepipeline/latest/userguide/connections-github.html

## Problem :  SiemPipelineStack-SiemPipelineStackPipelineBuildSy
Attached AdministratorAccess policy manually to SiemPipelineStack-SiemPipelineStackPipelineBuildSy
This should be done in code and only for the actions required.


## Dashboard Access

An SSH Tunnel is required according to:
https://docs.aws.amazon.com/opensearch-service/latest/developerguide/vpc.html

Instructions on how to access can be found here:
smb://evs-02.one.nca/nca_g/projects/nca-459-7/confidential/doc/aws

## Problem : Manual Internet Gateway setup
An 	igw-062e82276df3548a1 had to be setup manually.
The route from IP  5.149.3.0/24  to the gw-062e82276df3548a1 had to be setup in the main vpc route table rtb-07ef8c277a88c7d7a.
The security group sg-0da89a528c9caae23	aes-siem-vpc-sg required to open a ssh port 22 from ip 5.149.3.0/24 to SSH into tunnelhost

## Problem :  Lambda ZIP on github
The pipeline should build the lambda resources ZIP and deploy the zip. As there where issues on the path i pushed the ZIPs. 


# Confiugre Loader Lambda

I added a user.ini config file manually, its also in the source of the lambda, but we should create a separate lambda layer for this.  
According to https://github.com/netceteragroup/siem-on-amazon-opensearch-service/blob/main/docs/configure_siem.md

## Problem :  Lmabda had no access to the VPCFlowLog logs
Attached AdministratorAccess policy manually to SiemStageProd-MyAesSiemSt-LambdaEsLoaderServiceRol-N2ZF9IRQQ5EX