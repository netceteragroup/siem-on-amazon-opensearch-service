import os

import aws_cdk as cdk
from constructs import Construct
from .aes_siem_stack import MyAesSiemStack


class SiemStage(cdk.Stage):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        MyAesSiemStack(self,
                       id='MyAesSiemStack',
                       description=f'SIEM on Amazon OpenSearch Service 2.9.0',
                       env=cdk.Environment(account=os.getenv('CDK_DEPLOY_ACCOUNT'),
                                           region=os.getenv('CDK_DEPLOY_REGION'))
                       )
