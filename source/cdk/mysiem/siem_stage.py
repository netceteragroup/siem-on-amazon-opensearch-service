import os

import aws_cdk as cdk
from constructs import Construct
from .aes_siem_stack import MyAesSiemStack


class SiemStage(cdk.Stage):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = "755880545038"
        region = "eu-central-1"
        MyAesSiemStack(self,
                       id='CNNAesSiemStack',
                       description=f'SIEM on Amazon OpenSearch Service 2.9.0',
                       env=cdk.Environment(account=account,region=region)
                       )
