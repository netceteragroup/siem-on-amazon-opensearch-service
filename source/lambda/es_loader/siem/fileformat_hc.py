# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
__copyright__ = ('Copyright Amazon.com, Inc. or its affiliates. '
                 'All Rights Reserved.')
__version__ = '2.9.0'
__license__ = 'MIT-0'
__author__ = 'Akihiro Nakajima'
__url__ = 'https://github.com/aws-samples/siem-on-amazon-opensearch-service'

import json
import csv
import copy
import re

from aws_lambda_powertools import Logger

from siem import FileFormatBase

logger = Logger(child=True)

# the hc filetype is introduced to handle messages copied by the Helecloud lambda functions into the s3 logging bucket
# the hc filetype flag !cannot! be combined with the via_cwl flag!
# the hc filetype flag can currently only handle JSON logs and VPCFlow logs in CVS format! all other formats will fail
# more formats can be added by adding IF statements for each logtype to the convert_lograw_to_dict function
class FileFormatHc(FileFormatBase):
    def __init__(self, rawdata=None, logconfig=None, logtype=None):
        super().__init__(rawdata, logconfig, logtype)
        self.json_delimiter = logconfig['json_delimiter']
        self.csv_delimiter = logconfig['csv_delimiter']

    @property
    def log_count(self):
        body: str = self.rawdata.read()
        if "message" in body:
            return 1
        else:
            return 0

    def extract_log(self, start, end, logmeta={}):
        decoder = json.JSONDecoder()
        self.rawdata.seek(0)
        body: str = self.rawdata.read()
        _w = json.decoder.WHITESPACE.match
        json_body = decoder.decode(body)

        for logEntry in json_body:
            if 'message' in logEntry:
                hc_logmeta = copy.copy(logmeta)
                hc_logmeta['hc_id'] = logEntry['id']
                hc_logmeta['hc_timestamp'] = logEntry['timestamp']
                yield (logEntry['message'], self.convert_lograw_to_dict(logEntry['message']), hc_logmeta)

    def convert_lograw_to_dict(self, lograw, logconfig=None):
        try:
            if self.logtype == 'vpcflowlogs':
                vpc_header = ("version", "account-id", "interface-id",
                              "srcaddr", "dstaddr", "srcport", "dstport",
                              "protocol", "packets", "bytes", "start",
                              "end", "action", "log-status")
                if self.csv_delimiter:
                    for x in csv.reader([lograw], delimiter=self.csv_delimiter):
                        lograw_tuple = x
                else:
                    lograw_tuple = lograw.split()

                logdict = dict(zip(vpc_header, lograw_tuple))
                return logdict

            logdict = json.loads(lograw)
            if any([i in logdict for i in ["detail-type", "detailType"]]) and "resources" in logdict:
                return logdict['detail']

            return logdict
        except json.decoder.JSONDecodeError as e:
            # this is probablly CWL log and trauncated by original log sender
            # such as opensearch audit log
            err = e
            if r'Invalid \escape' in str(e):
                try:
                    lograw = re.sub(r'([^\\])\\x', r'\1\\\\x', lograw)
                    logdict = json.loads(lograw, strict=False)
                    return logdict
                except json.decoder.JSONDecodeError as e:
                    err = e
            logger.warning('This log will be loaded, '
                           'but not parsed because of invalid json')
            logdict = {'__skip_normalization': True,
                       '__error_message': f'invalid json file: {str(err)}'}
            return logdict
