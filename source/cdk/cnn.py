#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import aws_cdk as cdk
from mysiem.siem_pipeline_stack import SiemPipelineStack

CDK_DEFAULT_REGION = os.getenv("CDK_DEFAULT_REGION", os.environ["AWS_DEFAULT_REGION"])
region = os.environ.get("CDK_DEPLOY_REGION", CDK_DEFAULT_REGION)
account = os.environ.get("CDK_DEPLOY_ACCOUNT", os.environ["CDK_DEFAULT_ACCOUNT"])

account = "755880545038"
region = "eu-central-1"
environment = cdk.Environment(account=account, region=region)
stackId = "SiemPipelineStack"
app = cdk.App()
SiemPipelineStack(app, stackId, env=environment)
app.synth()
