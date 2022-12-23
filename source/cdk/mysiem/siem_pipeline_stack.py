import aws_cdk as cdk
from constructs import Construct
from aws_cdk.pipelines import (
    CodePipeline,
    CodePipelineSource,
    ShellStep
)
from aws_cdk import (
    Stack,
    StackProps,
    aws_codecommit as codecommit
)
from aws_cdk.aws_iam import (
    ManagedPolicy,
    Role,
    ServicePrincipal,
    PolicyStatement,
    Effect,
    AnyPrincipal
)

from .siem_stage import SiemStage


class SiemPipelineStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        branchName = "cnn-deployment"
        githubUrl = "netceteragroup/siem-on-amazon-opensearch-service"
        githubConnection = "arn:aws:codestar-connections:eu-central-1:755880545038:connection/be70a04d-ba82-4574-ade5-9e5bc3685307"
        source = CodePipelineSource.connection(repo_string=githubUrl, branch=branchName, connection_arn=githubConnection)
        pipeline = CodePipeline(self, "SiemPipelineStack",
                                pipeline_name="SiemPipelineStack",
                                cross_account_keys=True,
                                synth=ShellStep("Synth",
                                                 input=source,
                                                 install_commands=[
                                                     "cd source/cdk",
                                                     "npm install -g aws-cdk",
                                                     "pip install -r requirements.txt"
                                                 ],
                                                 commands=["cdk synth"]
                                                 )
                                 )
        stage = SiemStage(self, "SiemStageProd")
        pipeline.add_stage(stage)
