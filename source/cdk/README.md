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

## Redploy and start from scratch
When you want to delete the OpenSearch Stack in Cloudformation some ressources wont be delted so you need to manualy perform this. 
Delete the Stack (can take up some time if there are issues)
Delete all s3 buckets
Delete the KMS Keys
Delete the LogGroups

# Manual changes to the Pipeline Setup

## Gihub Connection
The Github Connection in AWS Logging Account is bound to netceteragroup repository https://github.com/netceteragroup/siem-on-amazon-opensearch-service

Setup:
https://docs.aws.amazon.com/codepipeline/latest/userguide/connections-github.html

## Problem :  SiemPipelineStack-SiemPipelineStackPipelineBuildSy
Attached AdministratorAccess policy manually to SiemPipelineStack-SiemPipelineStackPipelineBuildSy
This should be done in code and only for the actions required.


## Dashboard Access

An SSH Tunnel is required to access the dasbhoard. Its done according to:
https://docs.aws.amazon.com/opensearch-service/latest/developerguide/vpc.html

Instructions on how to get certificates and credentials can be found here:
smb://evs-02.one.nca/nca_g/projects/nca-459-7/confidential/doc/aws

## Problem : Manual Internet Gateway setup
An internet gateway had to be setup manually and attached to the VPC.
The route to IP 5.149.3.0/24 from the internete gateway had to be setup in the main vpc route table.
All subnets need routes from 0.0.0.0/0 to the internet gateway.
The security group of the VPC required to open the ssh port 22 from cidr range 5.149.3.0/24 to create an tunnel over the EC2 tunnelhost to the Dashboard.
The EC2 tunnelhost requires a public IP and should be attached to the same VPC and Subnet as opensearch.

## Problem :  Lambda ZIP on github
The pipeline should build the lambda resources ZIP and deploy the zip. As there where issues on the path i pushed the ZIPs. 


# Configure Loader Lambda

I added a user.ini config file manually, its also in the source of the lambda, but we should create a separate lambda layer for this.  
According to https://github.com/netceteragroup/siem-on-amazon-opensearch-service/blob/main/docs/configure_siem.md

## Problem :  Lmabda had no access to the VPCFlowLog logs
Attached AdministratorAccess policy manually to SiemStageProd-MyAesSiemSt-LambdaEsLoaderServiceRol-N2ZF9IRQQ5EX

## Interact with OpenSearch API

Postman collection can be found in source/postman. The baseUrl can be set to the https://localhost:9200 and the SSL tunnel needs to be active.

##Confiugred AWS Services

### Application logs
Each application log needs to be configured according to 2 different possibilities

1. Must: Definition file user.ini
2. Optional: Python Script for parsing special logs

Doku:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_siem.md#loading-non-aws-services-logs

Local Testing:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_siem.md#loading-logs-from-the-s3-bucket-using-an-object-list

## NIP 

cn-core-log-euc1-s3-logging/CWLogs/835193632749/eks_cnn-nip-prod-euc1-eks_container-logs/


### Config 
Integrated without an issue.

### S3 AccessLogs
Integrated without an issue.
Very big and this lead to congestion, i had to delete the index. I limited the index to the prod accounts etc.

### CloudTrail
Integrated without an issue.

### Guard Duty

GuardDuty export to s3: Requires according permissions to access bucket, kms etc.
destination bucket: arn:aws:s3:::cn-core-log-euc1-s3-logging
KMS key used: arn:aws:kms:eu-central-1:264034061693:key/2d16c006-7ff7-44fa-b1c8-72a6c030573d

### Security Hub
We have to setup the log forwarding as it is described here:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_aws_service.md

### VPC Flow Logs
We have to setup the log forwarding as it is described here:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_aws_service.md#amazon-vpc-flow-logs

### ELB
We have to setup the log forwarding as it is described here:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_aws_service.md#elastic-load-balancing-elb

##RDS
We have to setup the log forwarding as it is described here:
https://github.com/aws-samples/siem-on-amazon-opensearch-service/blob/main/docs/configure_aws_service.md#6-database
