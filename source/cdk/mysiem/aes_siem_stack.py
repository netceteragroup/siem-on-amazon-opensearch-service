# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = ('Copyright Amazon.com, Inc. or its affiliates. '
                 'All Rights Reserved.')
__version__ = '2.9.0'
__license__ = 'MIT-0'
__author__ = 'Akihiro Nakajima'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

import aws_cdk as cdk
import boto3
from aws_cdk import (
    aws_cloudformation,
    aws_cloudwatch,
    aws_ec2,
    aws_events,
    aws_events_targets,
    aws_iam,
    aws_kms,
    aws_lambda,
    aws_lambda_event_sources,
    aws_logs,
    aws_s3,
    aws_s3_notifications,
    aws_sns,
    aws_sns_subscriptions,
    aws_sqs,
    aws_stepfunctions,
    aws_stepfunctions_tasks,
    region_info,
)
from constructs import Construct

print(__version__)

SOLUTION_NAME = f'SIEM on Amazon OpenSearch Service v{__version__}'
INDEX_METRICS_PERIOD_HOUR = 1

iam_client = boto3.client('iam')
ec2_resource = boto3.resource('ec2')
ec2_client = boto3.client('ec2')
lambda_client = boto3.client('lambda')


def validate_cdk_json(context):
    print('\ncdk.json validation for vpc configuration is starting...\n')
    vpc_type = context.node.try_get_context("vpc_type")
    if vpc_type == 'new':
        print('vpc_type:\t\t\tnew')
        return True
    elif vpc_type == 'import':
        print('vpc_type:\t\t\timport')
    else:
        raise Exception('vpc_type is invalid. You can use "new" or "import". '
                        'Exit. Fix and Try again')

    vpc_id = context.node.try_get_context("imported_vpc_id")
    vpc_client = ec2_resource.Vpc(vpc_id)
    print('checking vpc...')
    vpc_client.state
    print(f'checking vpc id...:\t\t{vpc_id}')
    is_dns_support = vpc_client.describe_attribute(
        Attribute='enableDnsSupport')['EnableDnsSupport']['Value']
    print(f'checking dns support...:\t{is_dns_support}')
    is_dns_hotname = vpc_client.describe_attribute(
        Attribute='enableDnsHostnames')['EnableDnsHostnames']['Value']
    print(f'checking dns hostname...:\t{is_dns_hotname}')
    if not is_dns_support or not is_dns_hotname:
        raise Exception('enable DNS Hostname and DNS Support. Exit...')
    print('checking vpc is...\t\t[PASS]\n')

    subnet_ids_from_the_vpc = []
    subnet_objs_from_the_vpc = vpc_client.subnets.all()
    for subnet_obj in subnet_objs_from_the_vpc:
        subnet_ids_from_the_vpc.append(subnet_obj.id)

    def get_pub_or_priv_subnet(routes_attrs):
        for route in routes_attrs:
            gateway = route.get('GatewayId')
            if gateway and gateway.startswith('igw-'):
                return 'public'
        return 'private'

    validation_result = True
    subnet_types = {}
    routetables = vpc_client.route_tables.all()
    for routetable in routetables:
        rt_client = ec2_resource.RouteTable(routetable.id)
        subnet_type = get_pub_or_priv_subnet(rt_client.routes_attribute)
        for attribute in rt_client.associations_attribute:
            subnetid = attribute.get('SubnetId', "")
            main = attribute.get('Main', "")
            if subnetid:
                subnet_types[subnetid] = subnet_type
            elif main:
                subnet_types['main'] = subnet_type

    print('checking subnet...')
    subnet_ids = get_subnet_ids(context)

    for subnet_id in subnet_ids:
        if subnet_id in subnet_ids_from_the_vpc:
            if subnet_id in subnet_types:
                subnet_type = subnet_types[subnet_id]
            else:
                subnet_type = subnet_types['main']
            if subnet_type == 'private':
                print(f'{subnet_id} is\tprivate')
            elif subnet_type == 'public':
                print(f'{subnet_id} is\tpublic')
                validation_result = False
        else:
            print(f'{subnet_id} is\tnot exist')
            validation_result = False
    if not validation_result:
        raise Exception('subnet is invalid. Modify it.')
    print('checking subnet is...\t\t[PASS]\n')


def get_subnet_ids(context):
    subnet_ids = []
    subnet_ids = context.node.try_get_context('imported_vpc_subnets')
    if not subnet_ids:
        # compatibility for v2.0.0
        sbunet1 = context.node.try_get_context('imported_vpc_subnet1')
        sbunet2 = context.node.try_get_context('imported_vpc_subnet2')
        sbunet3 = context.node.try_get_context('imported_vpc_subnet3')
        subnet_ids = [sbunet1['subnet_id'], sbunet2['subnet_id'],
                      sbunet3['subnet_id']]
    return subnet_ids


def get_subnets(context):
    subnets = []
    subnet_ids = get_subnet_ids(context)
    attributes = ec2_client.describe_subnets(SubnetIds=subnet_ids)
    for attribute in attributes['Subnets']:
        subnet_id = attribute['SubnetId']
        # get associated route id
        response = ec2_client.describe_route_tables(
            Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}])
        if len(response['RouteTables']) == 0:
            # get main route id
            vpc_id = context.node.try_get_context("imported_vpc_id")
            response = ec2_client.describe_route_tables(
                Filters=[
                    {'Name': 'association.main', 'Values': ['true']},
                    {'Name': 'vpc-id', 'Values': [vpc_id]},
                ])
        route_table_id = (
            response['RouteTables'][0]['Associations'][0]['RouteTableId'])

        subnet = aws_ec2.Subnet.from_subnet_attributes(
            context,
            id=subnet_id,
            subnet_id=subnet_id,
            availability_zone=attribute['AvailabilityZone'],
            ipv4_cidr_block=attribute['CidrBlock'],
            route_table_id=route_table_id)

        subnets.append(subnet)

    return subnets


def check_iam_role(pathprefix):
    role_iterator = iam_client.list_roles(PathPrefix=pathprefix)
    if len(role_iterator['Roles']) == 1:
        return True
    else:
        return False


def same_lambda_func_version(func_name):
    try:
        response = lambda_client.list_versions_by_function(
            FunctionName=func_name)
        exist_vers = response['Versions'][0]['Description'].split()
        new_ver = f'v{__version__}'
        if new_ver in exist_vers:
            return True
        else:
            return False
    except Exception:
        return False


class MyAesSiemStack(cdk.Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        if self.node.try_get_context('vpc_type'):
            validate_cdk_json(self)

        ES_LOADER_TIMEOUT = 600
        PARTITION = region_info.Fact.find(
            self.region, region_info.FactName.PARTITION)
        if not PARTITION:
            PARTITION = 'aws'
        ######################################################################
        # REGION mapping / ELB & Lambda Arch
        ######################################################################
        elb_id_temp = region_info.FactName.ELBV2_ACCOUNT
        elb_map_temp = region_info.RegionInfo.region_map(elb_id_temp)
        no_alb_log_account_list = [
            'ap-south-2', 'eu-central-2', 'eu-south-2', 'me-central-1']
        for acct in no_alb_log_account_list:
            elb_map_temp[acct] = '999999999999'
        region_dict = {}
        # https://aws-data-wrangler.readthedocs.io/en/stable/layers.html
        for region in elb_map_temp:
            # ELB account ID
            region_dict[region] = {'ElbV2AccountId': elb_map_temp[region]}
            arm = aws_lambda.Architecture.ARM_64.name
            x86 = aws_lambda.Architecture.X86_64.name
            # Lambda Arch
            if region in ('af-south-1', 'ap-east-1',
                          'ap-northeast-1', 'ap-northeast-2', 'ap-northeast-3',
                          'ap-south-1',
                          'ap-southeast-1', 'ap-southeast-2', 'ap-southeast-3',
                          'ca-central-1',
                          'eu-central-1', 'eu-north-1', 'eu-south-1',
                          'eu-west-1', 'eu-west-2', 'eu-west-3',
                          'me-south-1', 'sa-east-1',
                          'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2'):
                region_dict[region]['LambdaArch'] = arm
            else:
                region_dict[region]['LambdaArch'] = x86
        region_mapping = cdk.CfnMapping(
            scope=self, id='RegionMap', mapping=region_dict)

        has_lambda_architectures_prop = cdk.CfnCondition(
            self, "HasLambdaArchitecturesProp",
            expression=cdk.Fn.condition_not(
                cdk.Fn.condition_or(
                    cdk.Fn.condition_equals(
                        cdk.Aws.REGION, 'ap-south-2'),
                    cdk.Fn.condition_equals(
                        cdk.Aws.REGION, 'eu-central-2'),
                    cdk.Fn.condition_equals(
                        cdk.Aws.REGION, 'eu-south-2'),
                    cdk.Fn.condition_equals(
                        cdk.Aws.REGION, 'me-central-1'),
                )
            )
        )

        ######################################################################
        # get params
        ######################################################################
        allow_source_address = cdk.CfnParameter(
            self, 'AllowedSourceIpAddresses', allowed_pattern=r'^[0-9./\s]*',
            description=('Space-delimited list of CIDR blocks. This parameter '
                         'applies only during the initial deployment'),
            default='10.0.0.0/8 172.16.0.0/12 192.168.0.0/16')
        sns_email = cdk.CfnParameter(
            self, 'SnsEmail', allowed_pattern=r'^[0-9a-zA-Z@_\-\+\.]*',
            description=('Input your email as SNS topic, where Amazon '
                         'OpenSearch Service will send alerts to'),
            default='user+sns@example.com')
        geoip_license_key = cdk.CfnParameter(
            self, 'GeoLite2LicenseKey',
            allowed_pattern=r'^([0-9a-zA-Z]{16}|)$', default='x' * 16,
            max_length=16,
            description=("If you wolud like to enrich geoip locaiton such as "
                         "IP address's country, get a license key form MaxMind"
                         " and input the key"))
        reserved_concurrency = cdk.CfnParameter(
            self, 'ReservedConcurrency', default=10, type='Number',
            description=('Input lambda reserved concurrency for es-loader. '
                         'Increase this value if there are steady logs delay '
                         'despite withou errors'))
        otx_api_key = cdk.CfnParameter(
            self, 'OtxApiKey', allowed_pattern=r'^([0-9a-f,x]{64}|)$',
            default='x' * 64, max_length=64,
            description=('(experimental) '
                         'If you wolud like to download IoC from AlienVault '
                         'OTX, please enter OTX API Key. '
                         'See details: https://otx.alienvault.com'))
        enable_tor = cdk.CfnParameter(
            self, 'EnableTor', allowed_values=['true', 'false'],
            description=('(experimental) '
                         'Would you like to download TOR IoC? '
                         'See details: https://check.torproject.org/api/bulk'),
            default='false')
        enable_abuse_ch = cdk.CfnParameter(
            self, 'EnableAbuseCh', allowed_values=['true', 'false'],
            description=(
                '(experimental) '
                'Would you like to download IoC from abuse.ch? '
                'See details: https://feodotracker.abuse.ch/blocklist/'),
            default='false')
        ioc_download_interval = cdk.CfnParameter(
            self, 'IocDownloadInterval', type='Number',
            description=('(experimental) '
                         'Specify interval in minute to download IoC, '
                         'default is 720 miniutes ( = 12 hours ).'
                         'min is 30 minutes. '
                         'max is 10080 minutes ( = 7 days ).'),
            min_value=30, max_value=10080, default=720)

        ct_log_buckets = cdk.CfnParameter(
            self, 'ControlTowerLogBucketNameList',
            type='String',
            allowed_pattern=r'^[-0-9a-z.\s,]*$',
            description=(
                'Specify S3 log bucket names in the Log Archive account. '
                'Comma separated list. '
                '(e.g., aws-controltower-logs-123456789012-ap-northeast-1, '
                'aws-controltower-s3-access-logs-123456789012-ap-northeast-1 )'
            ),
            default='')
        ct_role_arn = cdk.CfnParameter(
            self, 'ControlTowerRoleArnForEsLoader',
            description=(
                'Specify IAM Role ARN to be assumed by aes-siem-es-loader. '
                '(e.g., arn:aws:iam::123456789012:role/ct-role-for-siem )'),
            allowed_pattern=r'^(arn:aws.*:iam::[0-9]{12}:role/.*|)$',
            default='')
        ct_log_sqs = cdk.CfnParameter(
            self, 'ControlTowerSqsForLogBuckets',
            type='String',
            allowed_pattern=r'^(arn:aws[0-9a-zA-Z:/_-]*|)$',
            description=(
                'Specify SQS ARN for S3 log buckets in Log Archive Account. '
                '(e.g., arn:aws:sqs:ap-northeast-1:12345678902:aes-siem-ct )'
            ),
            default='')

        sl_role_arn = cdk.CfnParameter(
            self, 'SecurityLakeRoleArn',
            description=(
                'Specify IAM Role ARN to be assumed by aes-siem-es-loader. '
                '(e.g., arn:aws:iam::123456789012:role/AmazonSecurityLake'
                '-00001111-2222-3333-5555-666677778888 )'),
            allowed_pattern=(r'^(arn:aws.*:iam::[0-9]{12}:role/AmazonSecurity'
                             r'Lake-[0-9a-f-]*|)$'),
            default='')
        sl_external_id = cdk.CfnParameter(
            self, 'SecurityLakeExternalId',
            description=(
                'Specify Security Lake external ID for cross account. '
                '(e.g., externalid123 )'),
            allowed_pattern=r'^([0-9a-zA-Z]*|)$',
            default='')
        sl_log_sqs = cdk.CfnParameter(
            self, 'SecurityLakeSubscriberSqs',
            type='String',
            allowed_pattern=(r'^(arn:aws.*:sqs:.*:[0-9]{12}:AmazonSecurity'
                             r'Lake-[0-9a-f-]*-Main-Queue|)$'),
            description=(
                'Specify SQS ARN of Security Lake Subscriber. '
                '(e.g., arn:aws:sqs:us-east-1:12345678902:AmazonSecurityLake'
                '-00001111-2222-3333-5555-666677778888-Main-Queue )'),
            default='')

        # Pretfify parameters
        self.template_options.metadata = {
            'AWS::CloudFormation::Interface': {
                'ParameterGroups': [
                    {'Label': {'default': 'Initial Deployment Parameters'},
                     'Parameters': [allow_source_address.logical_id]},
                    {'Label': {'default': 'Basic Configuration'},
                     'Parameters': [sns_email.logical_id,
                                    reserved_concurrency.logical_id]},
                    {'Label': {'default': 'Log Enrichment - optional'},
                     'Parameters': [geoip_license_key.logical_id,
                                    otx_api_key.logical_id,
                                    enable_tor.logical_id,
                                    enable_abuse_ch.logical_id,
                                    ioc_download_interval.logical_id]},
                    {'Label': {'default': ('Control Tower Integration '
                                           '- optional')},
                     'Parameters': [ct_log_buckets.logical_id,
                                    ct_log_sqs.logical_id,
                                    ct_role_arn.logical_id, ]},
                    {'Label': {'default': ('(Experimental) '
                                           'Security Lake Integration - '
                                           'optional')},
                     'Parameters': [sl_log_sqs.logical_id,
                                    sl_role_arn.logical_id,
                                    sl_external_id.logical_id, ]},
                ]
            }
        }

        aes_domain_name = self.node.try_get_context('aes_domain_name')
        bucket = f'{aes_domain_name}-{cdk.Aws.ACCOUNT_ID}'
        s3bucket_name_geo = f'{bucket}-geo'
        s3bucket_name_log = f'{bucket}-log'
        s3bucket_name_snapshot = f'{bucket}-snapshot'
        cfn_ct_aws_account = cdk.Fn.select(
            4, cdk.Fn.split(':', ct_role_arn.value_as_string))
        cfn_sl_aws_account = cdk.Fn.select(
            4, cdk.Fn.split(':', sl_role_arn.value_as_string))
        # no access logs by default
        s3bucket_name_access_logs = ''
        s3bucket_access_logs_prefix = ''

        # organizations / multiaccount
        org_id = self.node.try_get_context('organizations').get('org_id')
        org_mgmt_id = self.node.try_get_context(
            'organizations').get('management_id')
        org_member_ids = self.node.try_get_context(
            'organizations').get('member_ids')
        no_org_ids = self.node.try_get_context(
            'no_organizations').get('aws_accounts')
        no_org_ids.sort()

        # Overwrite default S3 bucket name as customer name
        temp_geo = self.node.try_get_context('s3_bucket_name').get('geo')
        if temp_geo:
            s3bucket_name_geo = temp_geo
        else:
            print('Using default bucket names')
        temp_log = self.node.try_get_context('s3_bucket_name').get('log')
        if temp_log:
            s3bucket_name_log = temp_log
        elif org_id or no_org_ids:
            s3bucket_name_log = f'{aes_domain_name}-{self.account}-log'
        else:
            print('Using default bucket names')
        temp_snap = self.node.try_get_context('s3_bucket_name').get('snapshot')
        if temp_snap:
            s3bucket_name_snapshot = temp_snap
        else:
            print('Using default bucket names')
        kms_cmk_alias = self.node.try_get_context('kms_cmk_alias')
        if not kms_cmk_alias:
            kms_cmk_alias = 'aes-siem-key'
            print('Using default key alais')

        temp_acc_logs_bucket = self.node.try_get_context('s3_access_logs_bucket_name')
        if temp_acc_logs_bucket:
            s3bucket_name_access_logs = temp_acc_logs_bucket
        temp_acc_logs_prefix = self.node.try_get_context('s3_access_logs_prefix')
        if temp_acc_logs_prefix:
            s3bucket_access_logs_prefix = temp_acc_logs_prefix

        ######################################################################
        # deploy VPC when context is defined as using VPC
        ######################################################################
        # vpc_type is 'new' or 'import' or None
        vpc_type = self.node.try_get_context('vpc_type')

        if vpc_type == 'new':
            is_vpc = True
            vpc_cidr = self.node.try_get_context('new_vpc_nw_cidr_block')
            vpc_cidr_blocks = [vpc_cidr]
            subnet_cidr_mask = int(
                self.node.try_get_context('new_vpc_subnet_cidr_mask'))
            is_vpc = True
            # VPC
            vpc_aes_siem = aws_ec2.Vpc(
                self, 'VpcAesSiem', cidr=vpc_cidr,
                max_azs=3, nat_gateways=0,
                subnet_configuration=[
                    aws_ec2.SubnetConfiguration(
                        subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED,
                        name='aes-siem-subnet', cidr_mask=subnet_cidr_mask)])
            subnet_id_1st = vpc_aes_siem.isolated_subnets[0].subnet_id
            vpc_subnets = aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED)
            vpc_aes_siem_opt = vpc_aes_siem.node.default_child.cfn_options
            vpc_aes_siem_opt.deletion_policy = cdk.CfnDeletionPolicy.RETAIN
            for subnet in vpc_aes_siem.isolated_subnets:
                subnet_opt = subnet.node.default_child.cfn_options
                subnet_opt.deletion_policy = cdk.CfnDeletionPolicy.RETAIN
        elif vpc_type == 'import':
            vpc_id = self.node.try_get_context('imported_vpc_id')
            vpc_aes_siem = aws_ec2.Vpc.from_lookup(
                self, 'VpcAesSiem', vpc_id=vpc_id)
            boto3_vpc = ec2_resource.Vpc(vpc_id)
            vpc_cidr_blocks = (
                [x['CidrBlock'] for x in boto3_vpc.cidr_block_association_set])
            subnet_id_1st = get_subnet_ids(self)[0]
            subnets = get_subnets(self)
            vpc_subnets = aws_ec2.SubnetSelection(subnets=subnets)

        if vpc_type:
            is_vpc = True
            # Security Group
            sg_vpc_noinbound_aes_siem = aws_ec2.SecurityGroup(
                self, 'AesSiemVpcNoinboundSecurityGroup',
                security_group_name='aes-siem-noinbound-vpc-sg',
                vpc=vpc_aes_siem)

            sg_vpc_aes_siem = aws_ec2.SecurityGroup(
                self, 'AesSiemVpcSecurityGroup',
                security_group_name='aes-siem-vpc-sg',
                vpc=vpc_aes_siem)
            for vpc_cidr_block in vpc_cidr_blocks:
                sg_vpc_aes_siem.add_ingress_rule(
                    peer=aws_ec2.Peer.ipv4(vpc_cidr_block),
                    connection=aws_ec2.Port.tcp(443),)
            sg_vpc_opt = sg_vpc_aes_siem.node.default_child.cfn_options
            sg_vpc_opt.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

            # VPC Endpoint
            if vpc_type == "new":
                vpc_aes_siem.add_gateway_endpoint(
                    'S3Endpoint', service=aws_ec2.GatewayVpcEndpointAwsService.S3,
                    subnets=[vpc_subnets])
                vpc_aes_siem.add_interface_endpoint(
                    'SQSEndpoint', security_groups=[sg_vpc_aes_siem],
                    service=aws_ec2.InterfaceVpcEndpointAwsService.SQS,)
        else:
            is_vpc = False

        is_vpc = cdk.CfnCondition(
            self, 'IsVpc', expression=cdk.Fn.condition_equals(is_vpc, True))
        """
        CloudFormation実行時の条件式の書き方
        ClassのBasesが aws_cdk.cdk.Resource の時は、
        node.default_child.cfn_options.condition = is_vpc
        ClassのBasesが aws_cdk.cdk.CfnResource の時は、
        cfn_options.condition = is_vpc
        """

        ######################################################################
        # create cmk of KMS to encrypt S3 bucket
        ######################################################################
        kms_aes_siem = aws_kms.Key(
            self, 'KmsAesSiemLog', description='CMK for SIEM solution',
            removal_policy=cdk.RemovalPolicy.RETAIN)

        aws_kms.Alias(
            self, 'KmsAesSiemLogAlias', alias_name=kms_cmk_alias,
            target_key=kms_aes_siem,
            removal_policy=cdk.RemovalPolicy.RETAIN)

        kms_aes_siem.add_to_resource_policy(
            aws_iam.PolicyStatement(
                sid='Allow GuardDuty to use the key',
                actions=['kms:GenerateDataKey'],
                principals=[aws_iam.ServicePrincipal(
                    'guardduty.amazonaws.com')],
                resources=['*'],),)

        kms_aes_siem.add_to_resource_policy(
            aws_iam.PolicyStatement(
                sid='Allow VPC Flow Logs to use the key',
                actions=['kms:Encrypt', 'kms:Decrypt', 'kms:ReEncrypt*',
                         'kms:GenerateDataKey*', 'kms:DescribeKey'],
                principals=[aws_iam.ServicePrincipal(
                    'delivery.logs.amazonaws.com')],
                resources=['*'],),)
        # basic policy
        key_policy_basic1 = aws_iam.PolicyStatement(
            sid='Allow principals in the account to decrypt log files',
            actions=['kms:DescribeKey', 'kms:ReEncryptFrom'],
            principals=[aws_iam.AccountPrincipal(
                account_id=cdk.Aws.ACCOUNT_ID)],
            resources=['*'],)
        kms_aes_siem.add_to_resource_policy(key_policy_basic1)

        # for Athena
        key_policy_athena = aws_iam.PolicyStatement(
            sid='Allow Athena to query s3 objects with this key',
            actions=['kms:Decrypt', 'kms:DescribeKey', 'kms:Encrypt',
                     'kms:GenerateDataKey*', 'kms:ReEncrypt*'],
            principals=[aws_iam.AccountPrincipal(
                account_id=cdk.Aws.ACCOUNT_ID)],
            resources=['*'],
            conditions={'ForAnyValue:StringEquals': {
                'aws:CalledVia': 'athena.amazonaws.com'}})
        kms_aes_siem.add_to_resource_policy(key_policy_athena)

        # for CloudTrail
        key_policy_trail1 = aws_iam.PolicyStatement(
            sid='Allow CloudTrail to describe key',
            actions=['kms:DescribeKey'],
            principals=[aws_iam.ServicePrincipal('cloudtrail.amazonaws.com')],
            resources=['*'],)
        kms_aes_siem.add_to_resource_policy(key_policy_trail1)

        key_policy_trail2 = aws_iam.PolicyStatement(
            sid=('Allow CloudTrail to encrypt logs'),
            actions=['kms:GenerateDataKey*'],
            principals=[aws_iam.ServicePrincipal(
                'cloudtrail.amazonaws.com')],
            resources=['*'],
            conditions={'StringLike': {
                'kms:EncryptionContext:aws:cloudtrail:arn': [
                    (f'arn:{PARTITION}:cloudtrail:*:{cdk.Aws.ACCOUNT_ID}:'
                     'trail/*')
                ]}})
        kms_aes_siem.add_to_resource_policy(key_policy_trail2)

        ######################################################################
        # create s3 bucket
        ######################################################################
        block_pub = aws_s3.BlockPublicAccess(
            block_public_acls=True,
            ignore_public_acls=True,
            block_public_policy=True,
            restrict_public_buckets=True
        )

        s3_access_logs_bucket = None
        if len(s3bucket_name_access_logs) > 0:
            s3_access_logs_bucket = aws_s3.Bucket(self, "AccessLogsBucket")

        # mimics LZ "all" lifecycle rule
        s3_lifecycle_rule = aws_s3.LifecycleRule(
            id="all",
            enabled=True,
            transitions=[
                aws_s3.Transition(
                    storage_class=aws_s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
                    transition_after=cdk.Duration.days(90),
                ),
                aws_s3.Transition(
                    storage_class=aws_s3.StorageClass.GLACIER,
                    transition_after=cdk.Duration.days(270),
                ),
            ],
            expiration=cdk.Duration.days(3650),
        )

        s3_geo = aws_s3.Bucket(
            self, 'S3BucketForGeoip', block_public_access=block_pub,
            bucket_name=s3bucket_name_geo,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # removal_policy=cdk.RemovalPolicy.DESTROY,
            # covers S3.9 requirement
            server_access_logs_bucket=s3_access_logs_bucket,
            server_access_logs_prefix=f'{s3bucket_access_logs_prefix}-geo',
            # covers S3.10 and S3.13
            lifecycle_rules=[s3_lifecycle_rule],
        )

        # create s3 bucket for log collector
        s3_log = aws_s3.Bucket(
            self, 'S3BucketForLog', block_public_access=block_pub,
            bucket_name=s3bucket_name_log, versioned=True,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # removal_policy=cdk.RemovalPolicy.DESTROY,
            # covers S3.9 requirement
            server_access_logs_bucket=s3_access_logs_bucket,
            server_access_logs_prefix=f'{s3bucket_access_logs_prefix}-log',
            # covers S3.10 and S3.13
            lifecycle_rules=[s3_lifecycle_rule],
        )

        # create s3 bucket for aes snapshot
        s3_snapshot = aws_s3.Bucket(
            self, 'S3BucketForSnapshot', block_public_access=block_pub,
            bucket_name=s3bucket_name_snapshot,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # removal_policy=cdk.RemovalPolicy.DESTROY,
            # covers S3.9 requirement
            server_access_logs_bucket=s3_access_logs_bucket,
            server_access_logs_prefix=f'{s3bucket_access_logs_prefix}-snapshot',
            # covers S3.10 and S3.13
            lifecycle_rules=[s3_lifecycle_rule],
        )

        ######################################################################
        # IAM Role
        ######################################################################
        # delopyment policy for lambda deploy-aes
        arn_prefix = (
            f'arn:{PARTITION}:logs:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}')
        loggroup_aes = f'log-group:/aws/aes/domains/{aes_domain_name}/*'
        loggroup_opensearch = (
            f'log-group:/aws/OpenSearchService/domains/{aes_domain_name}/*')
        loggroup_lambda = 'log-group:/aws/lambda/aes-siem-*'
        policydoc_create_loggroup = aws_iam.PolicyDocument(
            statements=[
                aws_iam.PolicyStatement(
                    actions=[
                        'logs:PutResourcePolicy',
                        'logs:DescribeLogGroups',
                        'logs:DescribeLogStreams'
                    ],
                    resources=[f'{arn_prefix}:*', ]
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        'logs:CreateLogGroup', 'logs:CreateLogStream',
                        'logs:PutLogEvents', 'logs:PutRetentionPolicy'],
                    resources=[
                        f'{arn_prefix}:{loggroup_aes}',
                        f'{arn_prefix}:{loggroup_opensearch}',
                        f'{arn_prefix}:{loggroup_lambda}',
                    ],
                )
            ]
        )

        opensearch_deployment_policy = aws_iam.PolicyDocument(
            statements=[
                aws_iam.PolicyStatement(
                    actions=['es:CreateDomain', 'es:DescribeDomain',
                             'es:ESHttp*', 'es:UpdateDomainConfig'],
                    resources=['*']
                ),
            ]
        )

        policydoc_crhelper = aws_iam.PolicyDocument(
            statements=[
                aws_iam.PolicyStatement(
                    actions=[
                        'lambda:AddPermission',
                        'lambda:RemovePermission',
                        'events:ListRules',
                        'events:PutRule',
                        'events:DeleteRule',
                        'events:PutTargets',
                        'events:RemoveTargets'],
                    resources=['*']
                )
            ]
        )

        # snaphot rule for AES
        policydoc_snapshot = aws_iam.PolicyDocument(
            statements=[
                aws_iam.PolicyStatement(
                    actions=['s3:ListBucket'],
                    resources=[s3_snapshot.bucket_arn]
                ),
                aws_iam.PolicyStatement(
                    actions=['s3:GetObject', 's3:PutObject',
                             's3:DeleteObject'],
                    resources=[s3_snapshot.bucket_arn + '/*']
                )
            ]
        )
        aes_siem_snapshot_role = aws_iam.Role(
            self, 'AesSiemSnapshotRole',
            role_name='aes-siem-snapshot-role',
            inline_policies={'s3access': policydoc_snapshot},
            assumed_by=aws_iam.ServicePrincipal(
                'opensearchservice.amazonaws.com')
        )

        policydoc_assume_snapshotrole = aws_iam.PolicyDocument(
            statements=[
                aws_iam.PolicyStatement(
                    actions=['iam:PassRole'],
                    resources=[aes_siem_snapshot_role.role_arn]
                ),
            ]
        )

        aes_siem_deploy_role_for_lambda = aws_iam.Role(
            self, 'AesSiemDeployRoleForLambda',
            role_name='aes-siem-deploy-role-for-lambda',
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    'service-role/AWSLambdaBasicExecutionRole'),
            ],
            inline_policies={
                'opensearch_deployment': opensearch_deployment_policy,
                'assume_snapshotrole': policydoc_assume_snapshotrole,
                's3access': policydoc_snapshot,
                'cwl_loggroup': policydoc_create_loggroup,
                'crhelper': policydoc_crhelper},
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com')
        )

        if vpc_type:
            aes_siem_deploy_role_for_lambda.add_managed_policy(
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    'service-role/AWSLambdaVPCAccessExecutionRole')
            )

        # for alert from Amazon OpenSearch Service
        aes_siem_sns_role = aws_iam.Role(
            self, 'AesSiemSnsRole',
            role_name='aes-siem-sns-role',
            assumed_by=aws_iam.ServicePrincipal(
                'opensearchservice.amazonaws.com')
        )
        kms_aes_siem.grant(aes_siem_sns_role,
                           'kms:Decrypt', 'kms:GenerateDataKey')

        # EC2 role
        if self.region.startswith('cn-'):
            ec2_sp = 'ec2.amazonaws.com.cn'
        else:
            ec2_sp = 'ec2.amazonaws.com'
        aes_siem_es_loader_ec2_role = aws_iam.Role(
            self, 'AesSiemEsLoaderEC2Role',
            role_name='aes-siem-es-loader-for-ec2',
            assumed_by=aws_iam.ServicePrincipal(ec2_sp),
        )

        aws_iam.CfnInstanceProfile(
            self, 'AesSiemEsLoaderEC2InstanceProfile',
            instance_profile_name=aes_siem_es_loader_ec2_role.role_name,
            roles=[aes_siem_es_loader_ec2_role.role_name]
        )

        ######################################################################
        # in VPC
        ######################################################################
        aes_role_exist = check_iam_role(
            '/aws-service-role/opensearchservice.amazonaws.com/')
        if vpc_type and not aes_role_exist:
            slr_aes = aws_iam.CfnServiceLinkedRole(
                self, 'AWSServiceRoleForAmazonOpenSearchService',
                aws_service_name='opensearchservice.amazonaws.com',
                description='Created by cloudformation of siem stack'
            )
            slr_aes.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

        ######################################################################
        # SQS for es-laoder's DLQ
        ######################################################################
        sqs_aes_siem_dlq = aws_sqs.Queue(
            self, 'AesSiemDlq', queue_name='aes-siem-dlq',
            encryption=aws_sqs.QueueEncryption.KMS_MANAGED,
            data_key_reuse=cdk.Duration.hours(24),
            retention_period=cdk.Duration.days(14))

        sqs_aes_siem_splitted_logs = aws_sqs.Queue(
            self, 'AesSiemSqsSplitLogs',
            queue_name='aes-siem-sqs-splitted-logs',
            encryption=aws_sqs.QueueEncryption.KMS_MANAGED,
            data_key_reuse=cdk.Duration.hours(24),
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=20, queue=sqs_aes_siem_dlq),
            visibility_timeout=cdk.Duration.seconds(ES_LOADER_TIMEOUT),
            retention_period=cdk.Duration.days(14))

        ######################################################################
        # Setup Lambda
        ######################################################################
        # setup lambda of es_loader
        lambda_es_loader_vpc_kwargs = {}
        if vpc_type:
            lambda_es_loader_vpc_kwargs = {
                'security_groups': [sg_vpc_noinbound_aes_siem],
                'vpc': vpc_aes_siem,
                'vpc_subnets': vpc_subnets,
            }

        function_name = 'aes-siem-es-loader'
        lambda_es_loader = aws_lambda.Function(
            self, 'LambdaEsLoader', **lambda_es_loader_vpc_kwargs,
            function_name=function_name,
            description=f'{SOLUTION_NAME} / es-loader',
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/es_loader.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/es_loader'),
            handler='index.lambda_handler',
            memory_size=2048,
            timeout=cdk.Duration.seconds(ES_LOADER_TIMEOUT),
            reserved_concurrent_executions=(
                reserved_concurrency.value_as_number),
            dead_letter_queue_enabled=True,
            dead_letter_queue=sqs_aes_siem_dlq,
            environment={
                'GEOIP_BUCKET': s3bucket_name_geo, 'LOG_LEVEL': 'info',
                'POWERTOOLS_LOGGER_LOG_EVENT': 'false',
                'POWERTOOLS_SERVICE_NAME': 'es-loader',
                'POWERTOOLS_METRICS_NAMESPACE': 'SIEM',
                'CONTROL_TOWER_ROLE_SESSION_NAME': 'aes-siem-es-loader',
                'CONTROL_TOWER_ROLE_ARN': ct_role_arn.value_as_string,
                'CONTROL_TOWER_LOG_BUCKETS': ct_log_buckets.value_as_string,
                'SECURITY_LAKE_ROLE_SESSION_NAME': 'aes-siem-es-loader',
                'SECURITY_LAKE_ROLE_ARN': sl_role_arn.value_as_string,
                'SECURITY_LAKE_EXTERNAL_ID': (
                    sl_external_id.value_as_string),
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_es_loader.current_version
        lambda_es_loader.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )

        # send only
        # sqs_aes_siem_dlq.grant(lambda_es_loader, 'sqs:SendMessage')
        # send and reieve. but it must be loop
        sqs_aes_siem_dlq.grant(
            lambda_es_loader, 'sqs:SendMessage', 'sqs:ReceiveMessage',
            'sqs:DeleteMessage', 'sqs:GetQueueAttributes')

        sqs_aes_siem_splitted_logs.grant(
            lambda_es_loader, 'sqs:SendMessage', 'sqs:ReceiveMessage',
            'sqs:DeleteMessage', 'sqs:GetQueueAttributes')

        lambda_es_loader.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                sqs_aes_siem_splitted_logs, batch_size=1))

        # es-loaer on EC2 role
        sqs_aes_siem_dlq.grant(
            aes_siem_es_loader_ec2_role, 'sqs:GetQueue*', 'sqs:ListQueues*',
            'sqs:ReceiveMessage*', 'sqs:DeleteMessage*')

        # add pandas layer lambda
        function_name = 'aes-siem-add-pandas-layer'
        arn_pan = [
            f'arn:{PARTITION}:lambda:*:*:layer:AWSDataWrangler-*',
            f'arn:{PARTITION}:lambda:*:*:layer:AWSSDKPandas-*',
        ]
        lambda_add_pandas_layer_role = aws_iam.Role(
            self, "LambdaAddPandasLayerRole",
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    'service-role/AWSLambdaBasicExecutionRole')],
            inline_policies={
                'add-pandas-layer-policy': aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            actions=['lambda:UpdateFunctionConfiguration',
                                     'lambda:GetFunction'],
                            resources=[lambda_es_loader.function_arn]),
                        aws_iam.PolicyStatement(
                            actions=['lambda:PublishLayerVersion'],
                            resources=arn_pan,),
                        aws_iam.PolicyStatement(
                            actions=['lambda:ListLayers',
                                     'lambda:GetLayerVersion'],
                            resources=['*']),
                        aws_iam.PolicyStatement(
                            actions=["s3:Get*", "s3:List*"],
                            resources=['*']
                        )])},
            assumed_by=aws_iam.ServicePrincipal('lambda.amazonaws.com')
        )
        lambda_add_pandas_layer = aws_lambda.Function(
            self, 'LambdaAddPandasLayer',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / add-pandas-layer',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/add_pandas_layer.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/add_pandas_layer'),
            handler='lambda_function.lambda_handler',
            memory_size=128,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={
                'GEOIP_BUCKET': s3bucket_name_geo
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
            role=lambda_add_pandas_layer_role,
        )
        if not same_lambda_func_version(function_name):
            lambda_add_pandas_layer.current_version
        lambda_add_pandas_layer.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        # add pandas layer by execute cfn custom resource
        excec_lambda_add_layer = aws_cloudformation.CfnCustomResource(
            self, 'ExecLambdaAddPandasLayer',
            service_token=lambda_add_pandas_layer.function_arn,)
        excec_lambda_add_layer.add_override(
            'Properties.ConfigVersion', __version__)
        excec_lambda_add_layer.node.add_dependency(lambda_es_loader)
        excec_lambda_add_layer.node.add_dependency(
            lambda_add_pandas_layer_role)

        # setup lambda of es_loader_stopper
        function_name = 'aes-siem-es-loader-stopper'
        lambda_es_loader_stopper = aws_lambda.Function(
            self, 'LambdaEsLoaderStopper',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / es-loader-stopper',
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/es_loader_stopper.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/es_loader_stopper'),
            handler='index.lambda_handler',
            memory_size=128,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={
                'ES_LOADER_FUNCTION_ARN': lambda_es_loader.function_arn,
                'ES_LOADER_RESERVED_CONCURRENCY': (
                    reserved_concurrency.value_as_string)
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_es_loader_stopper.current_version
        lambda_es_loader_stopper.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        function_name = 'aes-siem-geoip-downloader'
        lambda_geo = aws_lambda.Function(
            self, 'LambdaGeoipDownloader',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / geoip-downloader',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/geoip_downloader.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/geoip_downloader'),
            handler='index.lambda_handler',
            memory_size=320,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={
                's3bucket_name': s3bucket_name_geo,
                'license_key': geoip_license_key.value_as_string,
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_geo.current_version
        lambda_geo.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        # IOC StepFunctions
        function_name = 'aes-siem-ioc-plan'
        lambda_ioc_plan = aws_lambda.Function(
            self, 'LambdaIocPlan',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / ioc-plan',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/ioc_database.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/ioc_database'),
            handler='lambda_function.plan',
            memory_size=128,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={
                'GEOIP_BUCKET': s3bucket_name_geo,
                'OTX_API_KEY': otx_api_key.value_as_string,
                'TOR': enable_tor.value_as_string,
                'ABUSE_CH': enable_abuse_ch.value_as_string,
                'LOG_LEVEL': 'INFO'
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_ioc_plan.current_version
        lambda_ioc_plan.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        function_name = 'aes-siem-ioc-download'
        lambda_ioc_download = aws_lambda.Function(
            self, 'LambdaIocDownload',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / ioc-download',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/ioc_database.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/ioc_database'),
            handler='lambda_function.download',
            memory_size=256,
            timeout=cdk.Duration.seconds(900),
            environment={
                'GEOIP_BUCKET': s3bucket_name_geo,
                'OTX_API_KEY': otx_api_key.value_as_string,
                'LOG_LEVEL': 'INFO'
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_ioc_download.current_version
        lambda_ioc_download.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        function_name = 'aes-siem-ioc-createdb'
        lambda_ioc_createdb = aws_lambda.Function(
            self, 'LambdaIocCreatedb',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / ioc-createdb',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/ioc_database.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/ioc_database'),
            handler='lambda_function.createdb',
            memory_size=1024,
            timeout=cdk.Duration.seconds(900),
            environment={
                'GEOIP_BUCKET': s3bucket_name_geo,
                'LOG_LEVEL': 'INFO'
            },
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_ioc_createdb.current_version

        lambda_ioc_createdb.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        task_ioc_plan = aws_stepfunctions_tasks.LambdaInvoke(
            self, "IocPlan",
            payload=aws_stepfunctions.TaskInput.from_text(''),
            lambda_function=lambda_ioc_plan,
            output_path="$.Payload"
        )
        ioc_not_found = aws_stepfunctions.Condition.is_not_present(
            "$.mapped[0].ioc")
        skip_download_state = aws_stepfunctions.Pass(self, "SkipDownload")
        map_download = aws_stepfunctions.Map(
            self, 'MapDownload',
            items_path=aws_stepfunctions.JsonPath.string_at("$.mapped"),
            parameters={"mapped.$": "$$.Map.Item.Value"},
            max_concurrency=4,
        )
        task_ioc_download = aws_stepfunctions_tasks.LambdaInvoke(
            self, "IocDownload",
            lambda_function=lambda_ioc_download,
            output_path="$.Payload",
            timeout=cdk.Duration.seconds(899),
        )
        ignore_timeout_state = aws_stepfunctions.Pass(self, "IgnoreTimeout")
        task_ioc_download.add_catch(
            ignore_timeout_state, errors=['States.Timeout'],
            result_path='$.catcher')
        task_ioc_createdb = aws_stepfunctions_tasks.LambdaInvoke(
            self, "IocCreatedb",
            lambda_function=lambda_ioc_createdb,
            output_path=None)
        definition = task_ioc_plan\
            .next(aws_stepfunctions.Choice(self, "need to download?")
                  .when(ioc_not_found, skip_download_state)
                  .otherwise(map_download.next(task_ioc_createdb)))
        map_download.iterator(task_ioc_download)
        ioc_state_machine_log_group = aws_logs.LogGroup(
            self, "IocStateMachineLogGroup",
            log_group_name='/aws/vendedlogs/states/aes-siem-ioc-logs',
            retention=aws_logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY)
        ioc_state_machine = aws_stepfunctions.StateMachine(
            self, "IocStateMachine",
            state_machine_name='aes-siem-ioc-state-machine',
            definition=definition, timeout=cdk.Duration.minutes(60),
            logs=aws_stepfunctions.LogOptions(
                destination=ioc_state_machine_log_group,
                level=aws_stepfunctions.LogLevel.ALL))

        # setup lambda of opensearch index metrics
        function_name = 'aes-siem-index-metrics-exporter'
        lambda_metrics_exporter = aws_lambda.Function(
            self, 'LambdaMetricsExporter', **lambda_es_loader_vpc_kwargs,
            function_name=function_name,
            description=f'{SOLUTION_NAME} / index-metrics-exporter',
            runtime=aws_lambda.Runtime.PYTHON_3_9,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/index_metrics_exporter.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/index_metrics_exporter'),
            handler='index.lambda_handler',
            memory_size=256,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={'LOG_BUCKET': s3bucket_name_log,
                         'PERIOD_HOUR': str(INDEX_METRICS_PERIOD_HOUR)},
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_metrics_exporter.current_version
        lambda_metrics_exporter.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )

        ######################################################################
        # setup OpenSearch Service
        ######################################################################
        function_name = 'aes-siem-deploy-aes'
        lambda_deploy_es = aws_lambda.Function(
            self, 'LambdaDeployAES',
            function_name=function_name,
            description=f'{SOLUTION_NAME} / opensearch domain deployment',
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/deploy_es.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/deploy_es'),
            handler='index.aes_domain_handler',
            memory_size=128,
            timeout=cdk.Duration.seconds(300),
            reserved_concurrent_executions=1,
            environment={
                'accountid': cdk.Aws.ACCOUNT_ID,
                'aes_domain_name': aes_domain_name,
                'aes_admin_role': aes_siem_deploy_role_for_lambda.role_arn,
                'allow_source_address': allow_source_address.value_as_string,
            },
            role=aes_siem_deploy_role_for_lambda,
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_deploy_es.current_version
        lambda_deploy_es.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        lambda_deploy_es.add_environment(
            's3_snapshot', s3_snapshot.bucket_name)
        if vpc_type:
            lambda_deploy_es.add_environment(
                'vpc_subnet_id', subnet_id_1st)
            lambda_deploy_es.add_environment(
                'security_group_id', sg_vpc_aes_siem.security_group_id)

        # execute lambda_deploy_es to deploy Amaozon OpenSearch Service Domain
        aes_domain = aws_cloudformation.CfnCustomResource(
            self, 'AesSiemDomainDeployedR2',
            service_token=lambda_deploy_es.function_arn,)
        aes_domain.add_override('Properties.ConfigVersion', __version__)
        aes_domain.node.add_dependency(aes_siem_deploy_role_for_lambda)

        es_endpoint = aes_domain.get_att('es_endpoint').to_string()
        lambda_es_loader.add_environment('ES_ENDPOINT', es_endpoint)
        lambda_es_loader.add_environment(
            'SQS_SPLITTED_LOGS_URL', sqs_aes_siem_splitted_logs.queue_url)
        lambda_metrics_exporter.add_environment('ES_ENDPOINT', es_endpoint)

        function_name = 'aes-siem-configure-aes'
        lambda_configure_es_vpc_kwargs = {}
        if vpc_type:
            lambda_configure_es_vpc_kwargs = {
                'security_groups': [sg_vpc_noinbound_aes_siem],
                'vpc': vpc_aes_siem,
                'vpc_subnets': vpc_subnets}
        lambda_configure_es = aws_lambda.Function(
            self, 'LambdaConfigureAES', **lambda_configure_es_vpc_kwargs,
            function_name=function_name,
            description=f'{SOLUTION_NAME} / opensearch configuration',
            runtime=aws_lambda.Runtime.PYTHON_3_8,
            # architecture=aws_lambda.Architecture.X86_64,
            code=aws_lambda.Code.from_asset('../lambda/deploy_es.zip'),
            #code=aws_lambda.Code.from_asset('../lambda/deploy_es'),
            handler='index.aes_config_handler',
            memory_size=128,
            timeout=cdk.Duration.seconds(600),
            reserved_concurrent_executions=1,
            environment={
                'accountid': cdk.Aws.ACCOUNT_ID,
                'aes_domain_name': aes_domain_name,
                'aes_admin_role': aes_siem_deploy_role_for_lambda.role_arn,
                'es_loader_role': lambda_es_loader.role.role_arn,
                'metrics_exporter_role': lambda_metrics_exporter.role.role_arn,
                'es_endpoint': es_endpoint,
            },
            role=aes_siem_deploy_role_for_lambda,
            current_version_options=aws_lambda.VersionOptions(
                removal_policy=cdk.RemovalPolicy.RETAIN,
                description=__version__
            ),
        )
        if not same_lambda_func_version(function_name):
            lambda_configure_es.current_version
        lambda_configure_es.node.default_child.add_property_override(
            "Architectures",
            cdk.Fn.condition_if(
                has_lambda_architectures_prop.logical_id,
                [region_mapping.find_in_map(cdk.Aws.REGION, 'LambdaArch')],
                cdk.Aws.NO_VALUE
            )
        )
        lambda_configure_es.add_environment(
            's3_snapshot', s3_snapshot.bucket_name)
        if vpc_type:
            lambda_configure_es.add_environment(
                'vpc_subnet_id', subnet_id_1st)
            lambda_configure_es.add_environment(
                'security_group_id', sg_vpc_aes_siem.security_group_id)
        else:
            lambda_configure_es.add_environment('vpc_subnet_id', 'None')
            lambda_configure_es.add_environment('security_group_id', 'None')

        aes_config = aws_cloudformation.CfnCustomResource(
            self, 'AesSiemDomainConfiguredR2',
            service_token=lambda_configure_es.function_arn,)
        aes_config.add_override('Properties.ConfigVersion', __version__)
        aes_config.add_depends_on(aes_domain)
        aes_config.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

        es_arn = (f'arn:{PARTITION}:es:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}'
                  f':domain/{aes_domain_name}')
        # grant permission to es_loader role
        inline_policy_to_load_entries_into_es = aws_iam.Policy(
            self, 'aes-siem-policy-to-load-entries-to-es',
            policy_name='aes-siem-policy-to-load-entries-to-es',
            statements=[
                aws_iam.PolicyStatement(
                    actions=['es:ESHttp*'],
                    resources=[es_arn + '/*', ]),
            ]
        )
        lambda_es_loader.role.attach_inline_policy(
            inline_policy_to_load_entries_into_es)
        aes_siem_es_loader_ec2_role.attach_inline_policy(
            inline_policy_to_load_entries_into_es)
        lambda_metrics_exporter.role.attach_inline_policy(
            inline_policy_to_load_entries_into_es)

        # grant permission to es_loader_stopper role
        inline_policy_to_stop_es_loader = aws_iam.Policy(
            self, 'aes-siem-policy-to-stop-es-loader',
            policy_name='aes-siem-policy-to-stop-es-loader',
            statements=[
                aws_iam.PolicyStatement(
                    actions=['lambda:PutFunctionConcurrency'],
                    resources=[lambda_es_loader.function_arn]),
            ]
        )
        lambda_es_loader_stopper.role.attach_inline_policy(
            inline_policy_to_stop_es_loader)

        # grant additional permission to es_loader role
        additional_kms_cmks = self.node.try_get_context('additional_kms_cmks')
        if additional_kms_cmks:
            inline_policy_access_to_additional_cmks = aws_iam.Policy(
                self, 'access_to_additional_cmks',
                policy_name='access_to_additional_cmks',
                statements=[
                    aws_iam.PolicyStatement(
                        actions=['kms:Decrypt'],
                        resources=sorted(set(additional_kms_cmks))
                    )
                ]
            )
            lambda_es_loader.role.attach_inline_policy(
                inline_policy_access_to_additional_cmks)
            aes_siem_es_loader_ec2_role.attach_inline_policy(
                inline_policy_access_to_additional_cmks)
        additional_buckets = self.node.try_get_context('additional_s3_buckets')

        if additional_buckets:
            buckets_list = []
            for bucket in additional_buckets:
                buckets_list.append(f'arn:{PARTITION}:s3:::{bucket}')
                buckets_list.append(f'arn:{PARTITION}:s3:::{bucket}/*')
            inline_policy_access_to_additional_buckets = aws_iam.Policy(
                self, 'access_to_additional_buckets',
                policy_name='access_to_additional_buckets',
                statements=[
                    aws_iam.PolicyStatement(
                        actions=['s3:GetObject*', 's3:GetBucket*', 's3:List*'],
                        resources=sorted(set(buckets_list))
                    )
                ]
            )
            lambda_es_loader.role.attach_inline_policy(
                inline_policy_access_to_additional_buckets)
            aes_siem_es_loader_ec2_role.attach_inline_policy(
                inline_policy_access_to_additional_buckets)

        kms_aes_siem.grant_decrypt(lambda_es_loader)
        kms_aes_siem.grant_decrypt(aes_siem_es_loader_ec2_role)
        kms_aes_siem.grant_encrypt(lambda_metrics_exporter)

        ######################################################################
        # s3 notification and grant permisssion
        ######################################################################
        s3_geo.grant_read_write(lambda_geo)
        s3_geo.grant_read_write(lambda_add_pandas_layer)
        s3_geo.grant_read_write(lambda_ioc_plan)
        s3_geo.grant_read_write(lambda_ioc_download)
        s3_geo.grant_read_write(lambda_ioc_createdb)
        s3_geo.grant_read(lambda_es_loader)
        s3_geo.grant_read(aes_siem_es_loader_ec2_role)
        s3_log.grant_read(lambda_es_loader)
        s3_log.grant_read(aes_siem_es_loader_ec2_role)
        s3_log.grant_write(lambda_metrics_exporter)

        # create s3 notification for es_loader
        notification = aws_s3_notifications.LambdaDestination(lambda_es_loader)

        # assign notification for the s3 PUT event type
        # most log system use PUT, but also CLB use POST & Multipart Upload
        s3_log.add_event_notification(
            aws_s3.EventType.OBJECT_CREATED, notification)

        if additional_buckets:
            for s3_bucket_name in additional_buckets:
                bucket = aws_s3.Bucket.from_bucket_name(
                    self,
                    id=s3_bucket_name,
                    bucket_name=s3_bucket_name
                )
                bucket.add_event_notification(
                    aws_s3.EventType.OBJECT_CREATED, notification)

        # Download geoip to S3 once by executing lambda_geo
        get_geodb = aws_cloudformation.CfnCustomResource(
            self, 'ExecLambdaGeoipDownloader',
            service_token=lambda_geo.function_arn,)
        get_geodb.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.RETAIN

        # Download geoip every 12 hours
        rule = aws_events.Rule(
            self, 'EventBridgeRuleLambdaGeoipDownloader',
            schedule=aws_events.Schedule.rate(cdk.Duration.hours(12)))
        rule.add_target(aws_events_targets.LambdaFunction(lambda_geo))

        # Download IOC Database every xxx minutes
        rule = aws_events.Rule(
            self, 'EventBridgeRuleStepFunctionsIoc',
            schedule=aws_events.Schedule.rate(
                cdk.Duration.minutes(ioc_download_interval.value_as_number)))
        rule.add_target(aws_events_targets.SfnStateMachine(ioc_state_machine))

        # collect index metrics every 1 hour
        rule_metrics_exporter = aws_events.Rule(
            self, 'EventBridgeRuleLambdaMetricsExporter',
            schedule=aws_events.Schedule.rate(
                cdk.Duration.hours(INDEX_METRICS_PERIOD_HOUR)))
        rule_metrics_exporter.add_target(
            aws_events_targets.LambdaFunction(lambda_metrics_exporter))

        ######################################################################
        # bucket policy
        ######################################################################
        # ALB, CLB
        s3_awspath = f'{s3_log.bucket_arn}/AWSLogs/{cdk.Aws.ACCOUNT_ID}'
        s3_awspath_w_prefix = (
            f'{s3_log.bucket_arn}/*/AWSLogs/{cdk.Aws.ACCOUNT_ID}')
        bucket_policy_alb1 = aws_iam.PolicyStatement(
            sid='ALB,CLB Policy',
            principals=[
                aws_iam.AccountPrincipal(
                    account_id=region_mapping.find_in_map(
                        cdk.Aws.REGION, 'ElbV2AccountId')),
            ],
            actions=['s3:PutObject'],
            resources=[f'{s3_awspath}/*', f'{s3_awspath_w_prefix}/*'],
        )
        bucket_policy_alb2 = aws_iam.PolicyStatement(
            sid='Policy For no ALB account region',
            principals=[
                aws_iam.ServicePrincipal(
                    'logdelivery.elasticloadbalancing.amazonaws.com')
            ],
            actions=['s3:PutObject'],
            resources=[f'{s3_log.bucket_arn}/*'],
            conditions={
                "StringEquals": {"aws:SourceAccount": [cdk.Aws.ACCOUNT_ID]}
            }
        )
        if self.region not in no_alb_log_account_list:
            s3_log.add_to_resource_policy(bucket_policy_alb1)
        else:
            s3_log.add_to_resource_policy(bucket_policy_alb2)

        # NLB / R53resolver / VPC Flow Logs
        bucket_policy_logdeliver1 = aws_iam.PolicyStatement(
            sid='AWSLogDelivery For NLB,R53Resolver,Flowlogs',
            principals=[aws_iam.ServicePrincipal(
                'delivery.logs.amazonaws.com')],
            actions=['s3:GetBucketAcl', 's3:ListBucket', 's3:PutObject'],
            resources=[s3_log.bucket_arn, f'{s3_log.bucket_arn}/*'],
            conditions={
                "StringEquals": {"aws:SourceAccount": [cdk.Aws.ACCOUNT_ID]}
            }
        )
        s3_log.add_to_resource_policy(bucket_policy_logdeliver1)

        # CloudTrail / Config
        bucket_policy_trail1 = aws_iam.PolicyStatement(
            sid='AWSLogDeliveryAclCheck For Cloudtrail, Config',
            principals=[
                aws_iam.ServicePrincipal('cloudtrail.amazonaws.com'),
                aws_iam.ServicePrincipal('config.amazonaws.com'),
            ],
            actions=['s3:GetBucketAcl', 's3:ListBucket'],
            resources=[s3_log.bucket_arn],
        )
        bucket_policy_trail2 = aws_iam.PolicyStatement(
            sid='AWSLogDeliveryWrite For CloudTrail, Config',
            principals=[
                aws_iam.ServicePrincipal('cloudtrail.amazonaws.com'),
                aws_iam.ServicePrincipal('config.amazonaws.com')],
            actions=['s3:PutObject'],
            resources=[f'{s3_log.bucket_arn}/*/*'],
            conditions={
                'StringEquals': {
                    "aws:SourceAccount": [cdk.Aws.ACCOUNT_ID],
                }
            }
        )
        s3_log.add_to_resource_policy(bucket_policy_trail1)
        s3_log.add_to_resource_policy(bucket_policy_trail2)

        # GuardDuty
        bucket_policy_gd1 = aws_iam.PolicyStatement(
            sid='Allow GuardDuty to put objects',
            principals=[aws_iam.ServicePrincipal('guardduty.amazonaws.com')],
            actions=['s3:GetBucketLocation', 's3:PutObject'],
            resources=[s3_log.bucket_arn, f'{s3_log.bucket_arn}/*'],
            conditions={
                'StringEquals': {"aws:SourceAccount": [cdk.Aws.ACCOUNT_ID]}
            }
        )
        s3_log.add_to_resource_policy(bucket_policy_gd1)

        # for IOC
        s3_geo.add_lifecycle_rule(
            enabled=True,
            expiration=cdk.Duration.days(8),
            id="delete-ioc-temp-files",
            prefix='IOC/tmp/'
        )

        # OpenSearch Doamin Snapshot
        bucket_policy_snapshot = aws_iam.PolicyStatement(
            sid='Allow OpenSearch Service to store snapshot',
            principals=[aes_siem_snapshot_role],
            actions=['s3:PutObject', 's3:GetObject', 's3:DeleteObject'],
            resources=[s3_snapshot.bucket_arn + '/*'],)
        s3_snapshot.add_to_resource_policy(bucket_policy_snapshot)

        ######################################################################
        # for multiaccount / organizaitons
        ######################################################################
        if org_id or no_org_ids:
            ##################################################################
            # KMS key policy for multiaccount / organizaitons
            ##################################################################
            # for CloudTrail
            cond_tail2 = self.make_resource_list(
                path=f'arn:{PARTITION}:cloudtrail:*:', tail=':trail/*',
                keys=self.list_without_none(org_mgmt_id, no_org_ids))
            key_policy_mul_trail2 = aws_iam.PolicyStatement(
                sid=('Allow CloudTrail to encrypt logs for multiaccounts'),
                actions=['kms:GenerateDataKey*'],
                principals=[aws_iam.ServicePrincipal(
                    'cloudtrail.amazonaws.com')],
                resources=['*'],
                conditions={'StringLike': {
                    'kms:EncryptionContext:aws:cloudtrail:arn': cond_tail2}})
            kms_aes_siem.add_to_resource_policy(key_policy_mul_trail2)

            # for replicaiton
            key_policy_rep1 = aws_iam.PolicyStatement(
                sid=('Enable cross account encrypt access for S3 Cross Region '
                     'Replication'),
                actions=['kms:Encrypt'],
                principals=self.make_account_principals(
                    org_mgmt_id, org_member_ids, no_org_ids),
                resources=['*'],)
            kms_aes_siem.add_to_resource_policy(key_policy_rep1)

            ##################################################################
            # Buckdet Policy for multiaccount / organizaitons
            ##################################################################
            s3_log_bucket_arn = f'arn:{PARTITION}:s3:::{s3bucket_name_log}'
            all_aws_accounts = self.list_without_none(
                org_mgmt_id, org_member_ids, no_org_ids)

            # for CloudTrail / Config
            if org_id:
                bucket_policy_org_trail1 = aws_iam.PolicyStatement(
                    sid='AWSCloudTrail, Config Write for Organizations',
                    principals=[
                        aws_iam.ServicePrincipal('cloudtrail.amazonaws.com'),
                        aws_iam.ServicePrincipal('config.amazonaws.com'),
                    ],
                    actions=['s3:PutObject'],
                    resources=[
                        f'{s3_log_bucket_arn}/{org_id}/AWSLogs/*/*',
                        f'{s3_log_bucket_arn}/*/{org_id}/AWSLogs/*/*',
                    ],
                )
                s3_log.add_to_resource_policy(bucket_policy_org_trail1)
            if len(no_org_ids) > 0:
                bucket_policy_org_trail2 = aws_iam.PolicyStatement(
                    sid='AWSCloudTrailWrite, Config for not org Multiaccounts',
                    principals=[
                        aws_iam.ServicePrincipal('cloudtrail.amazonaws.com'),
                        aws_iam.ServicePrincipal('config.amazonaws.com'),
                    ],
                    actions=['s3:PutObject'],
                    resources=[f'{s3_log_bucket_arn}/*/*'],
                    conditions={
                        'StringEquals': {"aws:SourceAccount": no_org_ids}
                    }
                )
                s3_log.add_to_resource_policy(bucket_policy_org_trail2)

            # for ALB
            resouces_list = self.make_resource_prefix_list(
                arn=s3_log_bucket_arn, tail='*', keys=all_aws_accounts)
            bucket_policy_mul_alb1 = aws_iam.PolicyStatement(
                sid='ALB,CLB multi Policy',
                principals=[
                    aws_iam.AccountPrincipal(
                        account_id=region_mapping.find_in_map(
                            cdk.Aws.REGION, 'ElbV2AccountId')),
                ],
                actions=['s3:PutObject'],
                resources=resouces_list,
            )
            # for no ALB account
            bucket_policy_mul_alb2 = aws_iam.PolicyStatement(
                sid='Policy for no ALB account for multiaccount',
                principals=[
                    aws_iam.ServicePrincipal(
                        'logdelivery.elasticloadbalancing.amazonaws.com')
                ],
                actions=['s3:PutObject'],
                resources=[f'{s3_log.bucket_arn}/*'],
                conditions={
                    "StringEquals": {"aws:SourceAccount": all_aws_accounts}
                }
            )
            if self.region not in no_alb_log_account_list:
                s3_log.add_to_resource_policy(bucket_policy_mul_alb1)
            else:
                s3_log.add_to_resource_policy(bucket_policy_mul_alb2)

            # NLB / R53resolver / VPC Flow Logs
            bucket_policy_mul_logdeliver1 = aws_iam.PolicyStatement(
                sid='AWSLogDeliveryAclCheck For mul NLB R53Resolver Flowlogs',
                principals=[aws_iam.ServicePrincipal(
                    'delivery.logs.amazonaws.com')],
                actions=['s3:GetBucketAcl', 's3:ListBucket', 's3:PutObject'],
                resources=[s3_log.bucket_arn, f'{s3_log.bucket_arn}/*'],
                conditions={
                    "StringEquals": {"aws:SourceAccount": all_aws_accounts}
                }
            )
            s3_log.add_to_resource_policy(bucket_policy_mul_logdeliver1)

            # for replication
            bucket_policy_rep1 = aws_iam.PolicyStatement(
                sid='PolicyForDestinationBucket / Permissions on objects',
                principals=self.make_account_principals(
                    org_mgmt_id, org_member_ids, no_org_ids),
                actions=['s3:ReplicateDelete', 's3:ReplicateObject',
                         's3:ReplicateTags', 's3:GetObjectVersionTagging',
                         's3:ObjectOwnerOverrideToBucketOwner'],
                resources=[f'{s3_log_bucket_arn}/*'])
            bucket_policy_rep2 = aws_iam.PolicyStatement(
                sid='PolicyForDestinationBucket / Permissions on bucket',
                principals=self.make_account_principals(
                    org_mgmt_id, org_member_ids, no_org_ids),
                actions=['s3:List*', 's3:GetBucketVersioning',
                         's3:PutBucketVersioning'],
                resources=[f'{s3_log_bucket_arn}'])
            s3_log.add_to_resource_policy(bucket_policy_rep1)
            s3_log.add_to_resource_policy(bucket_policy_rep2)

        ######################################################################
        # SNS topic for Amazon OpenSearch Service Alert
        ######################################################################
        sns_topic = aws_sns.Topic(
            self, 'SnsTopic', topic_name='aes-siem-alert',
            master_key=kms_aes_siem,
            display_name='AES SIEM')

        sns_topic.add_subscription(aws_sns_subscriptions.EmailSubscription(
            email_address=sns_email.value_as_string))
        sns_topic.grant_publish(aes_siem_sns_role)
        sns_topic.grant_publish(lambda_es_loader_stopper)

        ######################################################################
        # for es-loader-stopper
        ######################################################################
        # Add environment variables
        lambda_es_loader_stopper.add_environment(
            'AES_SIEM_ALERT_TOPIC_ARN', sns_topic.topic_arn)

        # CloudWatch Alarm
        total_free_storage_space_metric = aws_cloudwatch.Metric(
            metric_name='FreeStorageSpace', namespace='AWS/ES',
            statistic='Sum', period=cdk.Duration.minutes(1),
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID})
        total_free_storage_space_remains_low_alarm = aws_cloudwatch.Alarm(
            self, 'TotalFreeStorageSpaceRemainsLowAlarm',
            alarm_description=('Triggered when total free space for the '
                               'cluster remains less 200MB for 30 minutes.'),
            metric=total_free_storage_space_metric,
            evaluation_periods=30, threshold=200,  # 200 MByte
            comparison_operator=aws_cloudwatch
            .ComparisonOperator.LESS_THAN_OR_EQUAL_TO_THRESHOLD)

        # EventBridge
        es_loader_stopper_rule = aws_events.Rule(
            self, "EsLoaderStopperRule", event_pattern=aws_events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                resources=[
                    total_free_storage_space_remains_low_alarm.alarm_arn
                ]
            )
        )
        es_loader_stopper_rule.add_target(
            aws_events_targets.LambdaFunction(lambda_es_loader_stopper))

        ######################################################################
        # Control Tower
        ######################################################################
        is_control_tower_access = cdk.CfnCondition(
            self, "IsControlTowerAcccess",
            expression=cdk.Fn.condition_and(
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        ct_log_buckets.value_as_string, '')),
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        ct_role_arn.value_as_string, '')),
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        ct_log_sqs.value_as_string, '')),
            )
        )

        # grant additional permission to es_loader role for control tower
        inline_policy_controltower = aws_iam.Policy(
            self, 'access_to_control_tower_log_buckets',
            policy_name='access_to_control_tower',
            statements=[
                aws_iam.PolicyStatement(
                    actions=['sts:AssumeRole'],
                    resources=[ct_role_arn.value_as_string],
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "sqs:ReceiveMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueUrl",
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes"
                    ],
                    resources=[(f'arn:aws:sqs:*:{cfn_ct_aws_account}:*')],
                )
            ]
        )
        inline_policy_controltower.node.default_child.cfn_options.condition = (
            is_control_tower_access)
        lambda_es_loader.role.attach_inline_policy(
            inline_policy_controltower)

        source_mapping_for_ct = aws_lambda.EventSourceMapping(
            self, "EventSourceMappingForCT",
            target=lambda_es_loader,
            event_source_arn=ct_log_sqs.value_as_string,
        )
        source_mapping_for_ct.node.default_child.cfn_options.condition = (
            is_control_tower_access)

        ######################################################################
        # Amazon Security Lake
        ######################################################################
        is_security_lake_access = cdk.CfnCondition(
            self, "IsSecurityLakeAcccess",
            expression=cdk.Fn.condition_and(
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        sl_external_id.value_as_string, '')),
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        sl_role_arn.value_as_string, '')),
                cdk.Fn.condition_not(
                    cdk.Fn.condition_equals(
                        sl_log_sqs.value_as_string, '')),
            )
        )

        # grant additional permission to es_loader role for control tower
        inline_policy_securitylake = aws_iam.Policy(
            self, 'access_to_security_lake_log_buckets',
            policy_name='access_to_security_lake',
            statements=[
                aws_iam.PolicyStatement(
                    actions=['sts:AssumeRole'],
                    resources=[sl_role_arn.value_as_string],
                ),
                aws_iam.PolicyStatement(
                    actions=[
                        "sqs:ReceiveMessage",
                        "sqs:ChangeMessageVisibility",
                        "sqs:GetQueueUrl",
                        "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes"
                    ],
                    resources=[(f'arn:aws:sqs:*:{cfn_sl_aws_account}:*')],
                )
            ]
        )
        inline_policy_securitylake.node.default_child.cfn_options.condition = (
            is_security_lake_access)
        lambda_es_loader.role.attach_inline_policy(
            inline_policy_securitylake)

        source_mapping_for_ct2 = aws_lambda.EventSourceMapping(
            self, "EventSourceMappingForCT2",
            target=lambda_es_loader,
            event_source_arn=sl_log_sqs.value_as_string,
        )
        source_mapping_for_ct2.node.default_child.cfn_options.condition = (
            is_security_lake_access)

        ######################################################################
        # CloudWatch Dashboard
        ######################################################################
        self.create_cloudwatch_dashboard(
            aes_domain_name, lambda_es_loader, sqs_aes_siem_splitted_logs,
            sqs_aes_siem_dlq, total_free_storage_space_remains_low_alarm)

        ######################################################################
        # output of CFn
        ######################################################################
        kibanaurl = f'https://{es_endpoint}/_dashboards/'
        kibanaadmin = aes_domain.get_att('kibanaadmin').to_string()
        kibanapass = aes_domain.get_att('kibanapass').to_string()

        cdk.CfnOutput(self, 'RoleDeploy', export_name='role-deploy',
                      value=aes_siem_deploy_role_for_lambda.role_arn)
        cdk.CfnOutput(self, 'DashboardsUrl', export_name='dashboards-url',
                      value=kibanaurl)
        cdk.CfnOutput(self, 'DashboardsPassword',
                      export_name='dashboards-pass', value=kibanapass,
                      description=('Please change the password in OpenSearch '
                                   'Dashboards ASAP'))
        cdk.CfnOutput(self, 'DashboardsAdminID',
                      export_name='dashboards-admin', value=kibanaadmin)

    def list_without_none(self, *args):
        list_args = []
        for arg in args:
            if not arg:
                pass
            elif isinstance(arg, str) and arg:
                list_args.append(arg)
            elif isinstance(arg, list) and len(arg) > 0:
                list_args.extend(arg)
        list_args = sorted(list(set(list_args)))
        try:
            list_args.remove('')
        except Exception:
            pass
        return list_args

    def make_account_principals(self, *args):
        aws_ids = self.list_without_none(*args)
        account_principals = []
        for aws_id in sorted(set(aws_ids)):
            account_principals.append(
                aws_iam.AccountPrincipal(account_id=aws_id))
        return account_principals

    def make_resource_list(self, path=None, tail=None, keys=[]):
        aws_ids = self.list_without_none(keys)
        multi_s3path = []
        for aws_id in sorted(set(aws_ids)):
            multi_s3path.append(path + aws_id + tail)
        return multi_s3path

    def make_resource_prefix_list(self, arn=None, tail=None, keys=[]):
        aws_ids = self.list_without_none(keys)
        multi_s3path = []
        for aws_id in sorted(set(aws_ids)):
            multi_s3path.append(f'{arn}/AWSLogs/{aws_id}/{tail}')
            multi_s3path.append(f'{arn}/*/AWSLogs/{aws_id}/{tail}')
        return multi_s3path

    def create_cloudwatch_dashboard(
            self, aes_domain_name, lambda_es_loader,
            sqs_aes_siem_splitted_logs, sqs_aes_siem_dlq,
            total_free_storage_space_remains_low_alarm):
        example_dashboard_name = 'SIEM'
        # Create CloudWatch Dashboard to view SIEM Metrics
        cw_dashboard = aws_cloudwatch.Dashboard(
            self, 'SIEMDashboard', dashboard_name=example_dashboard_name)

        #######################################################################
        # CloudWatch Alarm
        #######################################################################
        cwl_alarm_widget = aws_cloudwatch.TextWidget(
            markdown='# CloudWatch Alarm', height=1, width=24)
        cwl_alarm_freespace_widget = aws_cloudwatch.AlarmWidget(
            title=f'{total_free_storage_space_remains_low_alarm.alarm_name}',
            alarm=total_free_storage_space_remains_low_alarm)

        #######################################################################
        # Lambda Function
        #######################################################################
        esloader_title_widget = aws_cloudwatch.TextWidget(
            markdown=f'# Lambda Function: {lambda_es_loader.function_name}',
            height=1, width=24)
        # invocations
        esloader_invocations_widget = aws_cloudwatch.GraphWidget(
            title='Invocations (Count)',
            height=4, width=12, period=cdk.Duration.seconds(60),
            left=[lambda_es_loader.metric_invocations()],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # Error count and success rate (%)
        success_rate = aws_cloudwatch.MathExpression(
            expression='100 - 100 * errors / MAX([errors, invocations])',
            using_metrics={
                'errors': lambda_es_loader.metric_errors(),
                'invocations': lambda_es_loader.metric_invocations()},
            label='Success rate (%)', color='#2ca02c')
        esloader_success_rate_widget = aws_cloudwatch.GraphWidget(
            title="Error count and success rate (%)",
            height=4, width=12, period=cdk.Duration.seconds(60),
            left=[lambda_es_loader.metric_errors(
                statistic='sum', color='#d13212', label='Errors (Count)')],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[success_rate],
            right_y_axis=aws_cloudwatch.YAxisProps(max=100, show_units=False))
        # throttles
        esloader_throttles_widget = aws_cloudwatch.GraphWidget(
            title='Throttles (Count)',
            height=4, width=12, period=cdk.Duration.seconds(60),
            left=[lambda_es_loader.metric_throttles()],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # duration
        esloader_duration_widget = aws_cloudwatch.GraphWidget(
            title='Duration (Milliseconds)',
            height=4, width=12, period=cdk.Duration.seconds(60),
            left=[lambda_es_loader.metric_duration(statistic='min'),
                  lambda_es_loader.metric_duration(statistic='avg'),
                  lambda_es_loader.metric_duration(statistic='max')],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        # concurrent exec
        esloader_concurrent_widget = aws_cloudwatch.GraphWidget(
            title='ConcurrentExecutions (Count)',
            height=4, width=12, period=cdk.Duration.seconds(60),
            left=[lambda_es_loader.metric_all_concurrent_executions(
                dimensions_map={
                    'FunctionName': lambda_es_loader.function_name})],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # timeout
        esloader_timeout_widget = aws_cloudwatch.LogQueryWidget(
            title='Longest 5 invocations',
            height=4, width=12,
            log_group_names=[f'/aws/lambda/{lambda_es_loader.function_name}'],
            view=aws_cloudwatch.LogQueryVisualizationType.TABLE,
            query_string="""fields @timestamp, @duration, @requestId
                | sort @duration desc
                | head 5""")

        #######################################################################
        # OpenSearch Service
        #######################################################################
        aos_title_widget = aws_cloudwatch.TextWidget(
            markdown=f'# OpenSearch Service: {aes_domain_name} domain',
            height=1, width=24)
        aos_title_widget_read = aws_cloudwatch.TextWidget(
            markdown='# Read / Search', height=1, width=12)
        aos_title_widget_write = aws_cloudwatch.TextWidget(
            markdown='# Write / Indexing', height=1, width=12)
        # CPUUtilization
        aos_cpu_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='CPUUtilization', statistic="max")
        aos_cpu_widget = aws_cloudwatch.GraphWidget(
            title='Data Node CPUUtilization (Cluster Max Percentage)',
            height=4, width=12,
            left=[aos_cpu_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(max=100, show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # JVMMemoryPressure
        aos_jvmmem_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='JVMMemoryPressure')
        aos_jvmmem_widget = aws_cloudwatch.GraphWidget(
            title='Data Node JVMMemoryPressure (Cluster Max Percentage)',
            height=4, width=12,
            left=[aos_jvmmem_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(max=100, show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # EBS
        aos_read_throughput_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ReadThroughput', statistic="max",
            label='ReadThroughput (Bytes/Second)')
        aos_write_throughput_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='WriteThroughput', statistic="max",
            label='WriteThroughput (Bytes/Second)')
        aos_read_iops_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ReadIOPS', statistic="max",
            label='ReadIOPS (Count/Second)')
        aos_write_iops_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='WriteIOPS', statistic="max",
            label='WriteIOPS (Count/Second)')
        aos_read_latency_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='Readatency', statistic="max",
            label='ReadLatency (Seconds)')
        aos_read_latency_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ReadLatency', statistic="max",
            label='ReadLatency (Seconds)')
        aos_write_latency_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='WriteLatency', statistic="max",
            label='WriteLatency (Seconds)')

        aos_disk_queue_depth_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='DiskQueueDepth', statistic="max",
            label='DiskQueueDepth (Count)')

        aos_read_throughput_iops_widget = aws_cloudwatch.GraphWidget(
            title='EBS Read Throughput / IOPS',
            height=4, width=12,
            left=[aos_read_throughput_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_read_iops_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        aos_write_throughput_iops_widget = aws_cloudwatch.GraphWidget(
            title='EBS Write Throughput / IOPS',
            height=4, width=12,
            left=[aos_write_throughput_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_write_iops_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        aos_read_latency_queue_widget = aws_cloudwatch.GraphWidget(
            title='EBS Read Latency / Disk Queue',
            height=4, width=12,
            left=[aos_read_latency_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_disk_queue_depth_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        aos_write_latency_queue_widget = aws_cloudwatch.GraphWidget(
            title='EBS Write Latency / Disk Queue',
            height=4, width=12,
            left=[aos_write_latency_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_disk_queue_depth_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))

        aos_cluster_disk_queue_throttle_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ThroughputThrottle', statistic="max",
            label='Cluster Disk ThroughputThrottle')
        aos_cluster_disk_queue_throttle_widget = aws_cloudwatch.GraphWidget(
            title='Cluster DiskThroughputThrottle',
            height=4, width=12,
            left=[aos_cluster_disk_queue_throttle_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            left_annotations=[
                aws_cloudwatch.HorizontalAnnotation(value=1)])
        # Search / Indexing Rate
        aos_search_rate_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='SearchRate', statistic="avg",
            label='SearchRate (Count)')
        aos_indexing_rate_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='IndexingRate', statistic="avg",
            label='IndexingRate (Count)')
        # Search / Indexing Latency
        aos_search_latency_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='SearchLatency', statistic="avg",
            label='SearchLatency (Milliseconds)')
        aos_indexing_latency_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='IndexingLatency', statistic="avg",
            label='IndexingLatency (Milliseconds)')
        aos_search_widget = aws_cloudwatch.GraphWidget(
            title='Search Rate / Latency (Node Average)',
            height=4, width=12,
            left=[aos_search_rate_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_search_latency_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        aos_indexing_widget = aws_cloudwatch.GraphWidget(
            title='Indexing Rate / Latency (Node Average)',
            height=4, width=12,
            left=[aos_indexing_rate_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            right=[aos_indexing_latency_metric],
            right_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        # Threadpool / Queue
        aos_searchqueue_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ThreadpoolSearchQueue', statistic="avg")
        aos_searchqueue_widget = aws_cloudwatch.GraphWidget(
            title='ThreadpoolReadQueue (Node Average Count)',
            height=4, width=12,
            left=[aos_searchqueue_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN,
            left_annotations=[
                aws_cloudwatch.HorizontalAnnotation(value=1000)])

        aos_writequeue_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ThreadpoolWriteQueue', statistic="avg")
        aos_writequeue_widget = aws_cloudwatch.GraphWidget(
            title='ThreadpoolWriteQueue (Node Average Count)',
            height=4, width=12,
            left=[aos_writequeue_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN,
            left_annotations=[
                aws_cloudwatch.HorizontalAnnotation(value=10000)])

        aos_shards_active_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='Shards.active', statistic="avg")
        aos_shards_activeprimary_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='Shards.activePrimary', statistic="avg")
        aos_active_shards_widget = aws_cloudwatch.GraphWidget(
            title='Active Shards Count',
            height=4, width=12,
            left=[aos_shards_active_metric,
                  aos_shards_activeprimary_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False))

        #######################################################################
        # ClusterIndexWritesBlocked
        #######################################################################
        aos_cluster_index_writes_blocked_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ClusterIndexWritesBlocked', statistic="avg")
        aos_cluster_index_writes_blocked_widget = aws_cloudwatch.GraphWidget(
            title='ClusterIndexWritesBlocked (Cluster Max Count)',
            height=4, width=12,
            left=[aos_cluster_index_writes_blocked_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        # Reject count
        aos_threadpool_search_rejected_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ThreadpoolSearchRejected',
            statistic="sum"
        )
        aos_threadpool_write_rejected_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ThreadpoolWriteRejected',
            statistic="sum"
        )
        aos_coordinating_write_rejected_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='CoordinatingWriteRejected',
            statistic="sum"
        )
        aos_primary_write_rejected_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='PrimaryWriteRejected',
            statistic="sum"
        )
        aos_replica_write_rejected_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID},
            metric_name='ReplicaWriteRejected',
            statistic="sum"
        )
        rejected_search_count_widget = aws_cloudwatch.GraphWidget(
            title='Threadpool Search Rejected Count (Node Total Count)',
            height=4, width=12,
            left=[aos_threadpool_search_rejected_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        rejected_indexing_count_widget = aws_cloudwatch.GraphWidget(
            title='Threadpool Indexing Rejected Count (Node Total Count)',
            height=4, width=12,
            left=[aos_threadpool_write_rejected_metric,
                  aos_coordinating_write_rejected_metric,
                  aos_primary_write_rejected_metric,
                  aos_replica_write_rejected_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False))
        # 40x 50x
        aos_4xx_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES', metric_name='4xx',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID})
        aos_5xx_metric = aws_cloudwatch.Metric(
            namespace='AWS/ES', metric_name='5xx',
            dimensions_map={'DomainName': aes_domain_name,
                            'ClientId': cdk.Aws.ACCOUNT_ID})
        aos_4xx_5xx_widget = aws_cloudwatch.GraphWidget(
            title='HTTP requests by error response code (Cluster Total Count)',
            height=4, width=12,
            left=[aos_4xx_metric, aos_5xx_metric],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False))

        #######################################################################
        # SQS
        #######################################################################
        sqs_widget = aws_cloudwatch.TextWidget(
            markdown='# SQS', height=1, width=24)
        sqs_splitted_log_visible_widget = aws_cloudwatch.GraphWidget(
            title=(f'{sqs_aes_siem_splitted_logs.queue_name}: '
                   'NumberOfMessagesReceived (Count)'),
            height=4, width=12,
            left=[sqs_aes_siem_splitted_logs
                  .metric_number_of_messages_received(statistic='sum')],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)
        sqs_dlq_visible_widget = aws_cloudwatch.GraphWidget(
            title=(f'{sqs_aes_siem_dlq.queue_name}: '
                   'ApproximateNumberOfMessagesVisible (Count)'),
            height=4, width=12,
            left=[sqs_aes_siem_dlq
                  .metric_approximate_number_of_messages_visible()],
            left_y_axis=aws_cloudwatch.YAxisProps(show_units=False),
            legend_position=aws_cloudwatch.LegendPosition.HIDDEN)

        #######################################################################
        # es-loader-error logs
        #######################################################################
        esloader_log_widget = aws_cloudwatch.TextWidget(
            markdown=('# Lambda Function Logs: '
                      f'{lambda_es_loader.function_name}'),
            height=1, width=24)
        esloader_log_critical_widget = aws_cloudwatch.LogQueryWidget(
            title='CRITICAL Logs',
            log_group_names=[f'/aws/lambda/{lambda_es_loader.function_name}'],
            width=24,
            view=aws_cloudwatch.LogQueryVisualizationType.TABLE,
            query_string="""fields @timestamp, message, s3_key
                | filter level == "CRITICAL"
                | sort @timestamp desc
                | limit 100""")
        esloader_log_error_widget = aws_cloudwatch.LogQueryWidget(
            title='ERROR Logs',
            width=24,
            log_group_names=[f'/aws/lambda/{lambda_es_loader.function_name}'],
            view=aws_cloudwatch.LogQueryVisualizationType.TABLE,
            query_string="""fields @timestamp, message, s3_key
                | filter level == "ERROR"
                | sort @timestamp desc
                | limit 100""")
        esloader_log_guide_widget = aws_cloudwatch.TextWidget(
            height=3, width=12,
            markdown=(
                '## Sample query\n'
                'To investigate critical/error log '
                'with CloudWatch Logs Insights\n\n'
                '```\n'
                'fields @timestamp, @message\n'
                '| filter s3_key == "copy s3_key and paste here"\n'
                'OR @requestId == "copy function_request_id and paste here"'
                '```'),)
        esloader_log_exception_error_widget = aws_cloudwatch.LogQueryWidget(
            title='Exception Logs',
            width=24,
            log_group_names=[f'/aws/lambda/{lambda_es_loader.function_name}'],
            view=aws_cloudwatch.LogQueryVisualizationType.TABLE,
            query_string=r"""fields @timestamp, @message
                | filter @message =~ /^\[ERROR]/
                | filter @message not like /No active exception to reraise/
                # exclude raise without Exception
                | sort @timestamp desc
                | limit 100""")

        # Add Widgets to CloudWatch Dashboard
        cw_dashboard.add_widgets(
            # CloudWatch Alarm
            cwl_alarm_widget,
            cwl_alarm_freespace_widget,
            # esloader_title_widget,
            esloader_title_widget,
            esloader_success_rate_widget, esloader_invocations_widget,
            esloader_duration_widget, esloader_throttles_widget,
            esloader_timeout_widget, esloader_concurrent_widget,
            # aos_title_widget,
            # cluster
            aos_title_widget,
            aos_cpu_widget, aos_jvmmem_widget,
            aos_4xx_5xx_widget, aos_active_shards_widget,
            aos_cluster_disk_queue_throttle_widget,
            aos_cluster_index_writes_blocked_widget,
            # ebs, instance
            aos_title_widget_read, aos_title_widget_write,
            aos_read_throughput_iops_widget, aos_write_throughput_iops_widget,
            aos_read_latency_queue_widget, aos_write_latency_queue_widget,
            aos_search_widget, aos_indexing_widget,
            aos_searchqueue_widget, aos_writequeue_widget,
            rejected_search_count_widget, rejected_indexing_count_widget,
            # sqs_widget
            sqs_widget,
            sqs_splitted_log_visible_widget, sqs_dlq_visible_widget,
            # esloader_log_widget
            esloader_log_widget,
            esloader_log_critical_widget,
            esloader_log_error_widget,
            esloader_log_guide_widget,
            esloader_log_exception_error_widget,
        )
