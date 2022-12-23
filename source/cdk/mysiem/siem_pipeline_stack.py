import aws_cdk as cdk
from constructs import Construct
from aws_cdk.pipelines import (
    CodePipeline,
    CodePipelineSource,
    ShellStep
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
                                synth=ShellStep("Synth",
                                                 input=source,
                                                 install_commands=[
                                                     "cd deployment/cdk-solution-helper",
                                                     "chmod +x step1-build-lambda-pkg.sh",
                                                     "./deployment/cdk-solution-helper/step1-build-lambda-pkg.sh",
                                                     "cd ../../source/cdk"
                                                     "npm install -g aws-cdk",
                                                     "pip install -r requirements.txt",
                                                 ],
                                                 commands=["cdk synth"],
                                                 primary_output_directory="source/cdk/cdk.out"
                                                )
                                )
        stage = SiemStage(self, "SiemStageProd")
        pipeline.add_stage(stage)
