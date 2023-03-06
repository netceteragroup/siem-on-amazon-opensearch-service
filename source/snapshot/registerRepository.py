import boto3
import requests
from requests_aws4auth import AWS4Auth

host = 'https://siem.log.cloud.netcetera.com/' # include https:// and trailing /
region = 'eu-central-1' # e.g. us-west-1
service = 'es'
credentials = boto3.Session().get_credentials()
awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, service, session_token=credentials.token)

# Register repository -

path = '_snapshot/domain-snapshot-repository' # the OpenSearch API endpoint
url = host + path

payload = {
    "type": "s3",
    "settings": {
        "bucket": "cnn-core-log-euc1-s3-cnn-siem-snapshot",
        "region": "eu-central-1",
        "role_arn": "arn:aws:iam::755880545038:role/aes-siem-snapshot-role",
        "server_side_encryption": True
    }
}

headers = {"Content-Type": "application/json"}

r = requests.put(url, auth=awsauth, json=payload, headers=headers)

print(r.status_code)
print(r.text)

# # Show Snapshot Repositories
# path = '_snapshot/'
# url = host + path
#
# r = requests.get(url, auth=awsauth)

# # Show available Snapshots in Repository
# path = '/_snapshot/cs-automated-enc/_all?pretty'
# path = '/_snapshot/cs-ultrawarm/_all?pretty'
# url = host + path
#
# r = requests.get(url, auth=awsauth)


# # Take snapshot
#
# path = '_snapshot/my-snapshot-repo-name/my-snapshot'
# url = host + path
#
# r = requests.put(url, auth=awsauth)
#
# print(r.text)
#
# # Delete index
# https://aws.amazon.com/premiumsupport/knowledge-center/opensearch-dashboards-error/
#
# path = 'my-index'
# url = host + path
#
# r = requests.delete(url, auth=awsauth)
#
# print(r.text)
#


# # Restore snapshot (all indexes with Dashboards and fine-grained access control)
#
# path = '_snapshot/my-snapshot-repo-name/my-snapshot/_restore'
# url = host + path
#
# payload = {
#   "include_global_state": True
# }
#
# headers = {"Content-Type": "application/json"}
#
# r = requests.post(url, auth=awsauth, json=payload, headers=headers)
#
# print(r.text)


# # Restore snapshot (all indexes except Dashboards and fine-grained access control)
#
# path = '_snapshot/my-snapshot-repo-name/my-snapshot/_restore'
# url = host + path
#
# payload = {
#   "indices": "-.kibana*,-.opendistro_security",
#   "include_global_state": False
# }
#
# headers = {"Content-Type": "application/json"}
#
# r = requests.post(url, auth=awsauth, json=payload, headers=headers)
#
# print(r.text)
#
# # Restore snapshot (one index)
#
# path = '_snapshot/my-snapshot-repo-name/my-snapshot/_restore'
# url = host + path
#
# payload = {"indices": "my-index"}
#
# headers = {"Content-Type": "application/json"}
#
# r = requests.post(url, auth=awsauth, json=payload, headers=headers)
#
# print(r.text)