import boto3
import subprocess

IS_PROD = False
QONTRACT_CLI_GET_AWS_ACCOUNT = 'qontract-cli --config config.debug.toml get aws-accounts'
QONTRACT_CLI_GET_AWS_CREDS = 'qontract-cli --config config.debug.toml get aws-creds'
QONTRACT_CLI_GET_RDS_FOR_AWS_ACCOUNT = 'qontract-cli --config config.debug.toml get rds-for-aws-account'

def run_command(command):
    p = subprocess.Popen(command, 
                        shell = True,
                        stdout = subprocess.PIPE,
                        stderr = subprocess.STDOUT)
    return p.stdout


def get_aws_accounts():
    aws_accounts_raw = run_command(QONTRACT_CLI_GET_AWS_ACCOUNT)
    aws_account_names = []
    for line in aws_accounts_raw:
        aws_account = line.decode('utf-8').split()
        aws_account_name = aws_account[0] 
        if '------' not in aws_account_name and aws_account_name != "NAME":
            aws_account_names.append(aws_account_name) 
    return aws_account_names

def get_aws_cred(aws_account_name):
    aws_cred_raw = run_command(QONTRACT_CLI_GET_AWS_CREDS + ' ' + aws_account_name).read()
    aws_cred_raw_list = \
        aws_cred_raw.decode('utf-8').replace("\n","").replace(" ","").split("export")[1:]
    aws_cred = {}
    aws_cred['AWS_ACCOUNT_NAME'] = aws_account_name
    for cred in aws_cred_raw_list:
        temp = cred.split('=')
        aws_cred[temp[0]] = temp[1]
    return aws_cred 

def get_rds_for_account(aws_account):
    rds_instances_raw = \
        run_command(QONTRACT_CLI_GET_RDS_FOR_AWS_ACCOUNT+' '+aws_account+' '+str(IS_PROD)) \
            .read().decode('utf-8').split()
    rds_instances = {}
    rds_instances['AWS_ACCOUNT_NAME'] = aws_account
    rds_instances['NAMES'] = []
    for line in rds_instances_raw:
        if '-------' not in line and line != "IDENTIFIER":
            rds_instances['NAMES'].append(line)
    return rds_instances

def get_boto3_client(creds, service = 'rds'):
    region = creds['AWS_REGION']
    client = boto3.client(service, region_name=region,
        aws_access_key_id=creds['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=creds['AWS_SECRET_ACCESS_KEY']
        )
    return client

def get_rds_instance_info(rds_client, db_names):
    rds_instances = rds_client.describe_db_instances(
    Filters=[
        {
            'Name': 'db-instance-id',
            'Values': db_names
        }
    ],)['DBInstances']
    return rds_instances

def get_pending_rds_instance_info(rds_client, db_names):
    rds_instances = rds_client.describe_pending_maintenance_actions(
        Filters=[
        {
            'Name': 'db-instance-id',
            'Values': db_names
        },
    ],)['PendingMaintenanceActions']
    return rds_instances
    

def schedule_maintenance(rds_client, arn, maintenance_type = 'system-update',
                         opt_in_type = 'next-maintenance'):
    for arn in rds_infos:
        rds_client.apply_pending_maintenance_action(
            ResourceIdentifier = arn,
            ApplyAction = maintenance_type,
            OptInType = opt_in_type
            )
        

aws_accounts = get_aws_accounts()
total_maintenance_scheduled = 0
for name in aws_accounts:
    rds_instances = get_rds_for_account(name)
    if rds_instances['NAMES']:
        cred = get_aws_cred(name)
        print('--------------------------------------------------------')
        print(f"{len(rds_instances['NAMES'])} RDS instances managed by A-I: \
                \n {rds_instances['NAMES']} in {name} AWS account")
        aws_rds_client = get_boto3_client(cred)
        rds_infos = get_pending_rds_instance_info(aws_rds_client, rds_instances['NAMES'])
        for rds in rds_infos:
            pending_maintenance_actions = rds['PendingMaintenanceActionDetails']
            for action in pending_maintenance_actions:
                if 'New Operating System update is available' in action['Description']: 
                    arn = rds['ResourceIdentifier']
                    db_name = arn.split(':')[-1]
                    total_maintenance_scheduled += 1
                    print(f'---{total_maintenance_scheduled}')
                    print(f"{db_name} pending maintenance, scheduleing OS upgrade in next maintenance window.")
                    #schedule_maintenance(aws_rds_client, rds['ResourceIdentifier'])
