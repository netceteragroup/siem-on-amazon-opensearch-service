#!/bin/sh
export ES_ENDPOINT=localhost
export AWS_ACCOUNT=755880545038
export LOG_BUCKET=cn-core-log-euc1-s3-logging
aws s3 ls  ${LOG_BUCKET}/CWLogs/835193632749/eks_cnn-nip-prod-euc1-eks_container-logs/nip-prod-silver-mercury.keycloak-prod-silver-mercury-1.keycloak/ --recursive > s3-list.txt

cd ../source/lambda/es_loader
#pip3 install -r requirements.txt -U -t .
#pip3 install pandas -U

./index.py -b ${LOG_BUCKET} -l ../../../deployment/s3-list.txt
