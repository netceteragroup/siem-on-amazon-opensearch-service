#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = ('Copyright Amazon.com, Inc. or its affiliates. '
                 'All Rights Reserved.')
__version__ = '2.10.1'
__license__ = 'MIT-0'
__author__ = 'Akihiro Nakajima'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

import os

import aws_cdk as cdk

from mysiem.aes_siem_stack import MyAesSiemStack

from constructs import Construct


class SiemPipelineStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


class SiemStage(cdk.Stage):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


app = cdk.App()
CDK_DEFAULT_REGION = os.getenv(
    "CDK_DEFAULT_REGION", os.environ["AWS_DEFAULT_REGION"])
region = os.environ.get("CDK_DEPLOY_REGION", CDK_DEFAULT_REGION)
account = os.environ.get(
    "CDK_DEPLOY_ACCOUNT", os.environ["CDK_DEFAULT_ACCOUNT"])
add_tags = os.environ.get("SIEM_ADD_TAGS", "")

# In order to have smooth migration from old deployment model, we have to
# follow the previously chosen naming conventions. It means having Application
# named "DeploySiemStageProd-CNNAesSiemStack" and CloudFormation stack named
# "DeploySiemStageProd-CNNAesSiemStack" wich manages resources with hierarchy:
# "DeploySiemStageProd --> CNNAesSiemStack".

# The upstream class which defines the stack. For regular deployments,
# uncomment it and delete additional classes defined above.

# MyAesSiemStack(app, "aes-siem",
#                description=f'SIEM on Amazon OpenSearch Service v{__version__}',
#                env=cdk.Environment(account=account, region=region))

siempipe = SiemPipelineStack(app, "SiemPipelineStack",
                             env=cdk.Environment(account=account, region=region))

siemstage = SiemStage(siempipe, "DeploySiemStageProd",
                      env=cdk.Environment(account=account, region=region))

MyAesSiemStack(siemstage, "CNNAesSiemStack",
               description=f'SIEM on Amazon OpenSearch Service v{__version__}',
               env=cdk.Environment(account=account, region=region))

for tag in add_tags.split(";"):
    tag_kv = tag.split("=")
    if len(tag_kv) == 2:
        cdk.Tags.of(app).add(tag_kv[0], tag_kv[1])

app.synth()
