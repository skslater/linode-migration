#!/usr/bin/python
#
#
# Copyright (c) 2012, Simon Slater
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


#
# The settings below MUST be changed to match your requirements
#
LINODE_API_KEY = ""
AWS_ACCESS_KEY = ""
AWS_SECRET_KEY = ""
HOSTMASTER_EMAIL = ""               # Used as SOA contact address

#
# To import only selected zones enter them in the list below
# ex. IMPORT_ZONES = [ "example.com", "example2.com" ]
#
IMPORT_ZONES = [ ]

#
# The settings below MAY be changed although the defaults should be ok
#
DEBUG_AWS = 0
DEBUG_LINODE = 0
DEBUG_XML = 0
INITIAL_ZONE_STATUS = 0             # 0=Disabled, 1=Active

#
# The following settings SHOULD NOT be changed unless you understand
# the implications
#
LINODE_API_URL = "https://api.linode.com/?api_key={0}"
AWS_ROUTE53_URL = "https://route53.amazonaws.com/2012-02-29{0}"
AWS_DATE_URL = "https://route53.amazonaws.com/date"
AWS_SIGNATURE_FORMAT = "AWS3-HTTPS AWSAccessKeyId={0},Algorithm={1},Signature={2}"
AWS_SIGNATURE_ALGORITHM = "HmacSHA256"

#
# End of settings
#

import json
import urllib2
import hmac
import hashlib
import base64
from xml.sax.handler import ContentHandler
from xml.sax import parseString
from urllib import urlencode

#
# Route53 XML Zone Parser
#
class AWSZoneParser(ContentHandler):

    def __init__(self):
        if DEBUG_XML: print("-- AWSZoneParser instantiated")
        self.inIdElement = 0
        self.inNameElement = 0
        self.xmlDepth = 0

    def startElement(self, name, attrs):
        self.xmlDepth = self.xmlDepth + 1
        if DEBUG_XML: print("--{0} <{1}>".format("--" * self.xmlDepth, name))
        if name == "Id":
            self.inIdElement = 1
            self.currentIdText = ''
        elif name == "Name":
            self.inNameElement = 1
            self.currentNameText = ''

    def characters(self, ch):
        if self.inIdElement:
            self.currentIdText = self.currentIdText + ch
        elif self.inNameElement:
            self.currentNameText = self.currentNameText + ch

    def endElement(self, name):
        if DEBUG_XML: print("--{0} <{1}>".format("--" * self.xmlDepth, name))
        if name == "Id":
            self.inIdElement = 0
            self.currentZoneId = self.currentIdText[self.currentIdText.rfind("/")+1:]
        elif name == "Name":
            self.inNameElement = 0
            self.currentZoneName = self.currentNameText.rstrip(".")
        elif name == 'HostedZone':
            process_aws_zone(self.currentZoneId, self.currentZoneName)
        self.xmlDepth = self.xmlDepth - 1

#
# Route53 XML RecordSet Parser
#
class AWSRecordSetParser(ContentHandler):

    def __init__(self, domainId, zoneName):
        if DEBUG_XML: print("-- AWSRecordSetParser instantiated")
        self.domainId = domainId
        self.zoneName = zoneName
        self.inNameElement = 0
        self.inTTLElement = 0
        self.inTypeElement = 0
        self.inValueElement = 0
        self.xmlDepth = 0

    def startElement(self, name, attrs):
        self.xmlDepth = self.xmlDepth + 1
        if DEBUG_XML: print("--{0} <{1}>".format("--" * self.xmlDepth, name))
        if name == 'Name':
            self.inNameElement = 1
            self.currentNameText = ''
        elif name == 'TTL':
            self.inTTLElement = 1
            self.currentTTLText = ''
        elif name == 'Type':
            self.inTypeElement = 1
            self.currentTypeText = ''
        elif name == 'Value':
            self.inValueElement = 1
            self.currentValueText = ''

    def characters(self, ch):
        if self.inNameElement:
            self.currentNameText = self.currentNameText + ch
        elif self.inTTLElement:
            self.currentTTLText = self.currentTTLText + ch
        elif self.inTypeElement:
            self.currentTypeText = self.currentTypeText + ch
        elif self.inValueElement:
            self.currentValueText = self.currentValueText + ch

    def endElement(self, name):
        if DEBUG_XML: print("--{0} <{1}>".format("--" * self.xmlDepth, name))
        if name == 'Name':
            self.inNameElement = 0
            self.currentName = self.currentNameText.rstrip(".")
        elif name == 'TTL':
            self.inTTLElement = 0
            self.currentTTL = int(self.currentTTLText)
        elif name == 'Type':
            self.inTypeElement = 0
            self.currentType = self.currentTypeText
        elif name == 'Value':
            self.inValueElement = 0
            self.currentValue = self.currentValueText
            linode_create_record(self.domainId, self.zoneName, self.currentName, self.currentType, self.currentTTL, self.currentValue)
        self.xmlDepth = self.xmlDepth - 1

#
# Send a request to AWS Route53 API
#
def execute_aws_request(requestPath):
    requestUrl = AWS_ROUTE53_URL.format(requestPath)
    if DEBUG_AWS: print("-- Sending request to AWS: {0}".format(requestUrl))
    requestObject = urllib2.Request(requestUrl)
    sign_aws_request(requestObject)
    responseObject = urllib2.urlopen(requestObject)
    responseData = responseObject.read()
    if DEBUG_AWS: print(responseData)
    return responseData

#
# Sign the AWS request with the API key
#
def sign_aws_request(requestObject):
    dateUrl = AWS_DATE_URL
    dateRequest = urllib2.Request(dateUrl)
    dateResponse = urllib2.urlopen(dateRequest)
    dateHeaders = dateResponse.info()
    awsDate = dateHeaders.getheader('Date')
    hmacDate = hmac.new(AWS_SECRET_KEY, awsDate, hashlib.sha256).digest()
    base64Date = base64.b64encode(hmacDate)
    requestObject.add_header('Date', awsDate)
    signature = AWS_SIGNATURE_FORMAT.format(AWS_ACCESS_KEY, AWS_SIGNATURE_ALGORITHM, base64Date)
    if DEBUG_AWS: print("Signature: {0}".format(signature))
    requestObject.add_header('X-Amzn-Authorization', signature)

#
# Send a request to the Linode API
#
def execute_linode_request(requestParams):
    requestUrl = LINODE_API_URL.format(LINODE_API_KEY)
    if requestParams and len(requestParams) > 0:
        requestUrl = "{0}&{1}".format(requestUrl, urlencode(requestParams))
    if DEBUG_LINODE: print("Request: {0}".format(requestUrl))
    linodeRequest = urllib2.Request(requestUrl)
    linodeResponse = urllib2.urlopen(linodeRequest)
    linodeData = linodeResponse.read()
    if DEBUG_LINODE: print(linodeData)
    return linodeData

#
# Create a new Linode DNS domain
#
def linode_create_domain(domainName):
    requestParams = {
        "action" : "domain.create",
        "domain" : domainName,
        "soa_email" : HOSTMASTER_EMAIL,
        "type" : "master",
        "status" : INITIAL_ZONE_STATUS
        }
    createResponse = execute_linode_request(requestParams)
    createJson = json.loads(createResponse)
    if createJson['ERRORARRAY']:
        errorCode = createJson['ERRORARRAY'][0]['ERRORCODE']
        errorMessage = createJson['ERRORARRAY'][0]['ERRORMESSAGE']
        print("Skipping: {0}".format(errorMessage))
        return None
    domainId = createJson['DATA']['DomainID']
    return domainId

#
# Begin the zone migration
#
def begin_zone_migration():
    zoneXmlText = execute_aws_request("/hostedzone")
    zoneXmlHandler = AWSZoneParser()
    parseString(zoneXmlText, zoneXmlHandler)

#
# Process a new zone with the specified id and name
#
def process_aws_zone(zoneId, zoneName):
    if IMPORT_ZONES and zoneName not in IMPORT_ZONES:
        print("Skipping zone {0} with id {1} (not in IMPORT_ZONES list)".format(zoneName, zoneId))
        return

    print("Processing zone {0} with id {1}".format(zoneName, zoneId))

    domainId = linode_create_domain(zoneName)            

    if not domainId: return

    recordXmlText = execute_aws_request("/hostedzone/{0}/rrset".format(zoneId))
    recordXmlHandler = AWSRecordSetParser(domainId, zoneName)
    parseString(recordXmlText, recordXmlHandler)

#
# Process a record for the given domain
#
def linode_create_record(domainId, zoneName, recordName, recordType, recordTTL, recordValue):
    if recordType == 'SOA': return
    if recordType == 'NS': return
    print("\tMigrating record (name={0}, type={1}, ttl={2}, value={3}) to domain {4} (id={5})".format(recordName, recordType, recordTTL, recordValue, zoneName, domainId))
    requestParams = {
        "api_action" : "domain.resource.create",
        "domainid" : domainId,
        "type" : recordType,
        "name" : recordName,
        "ttl_sec" : recordTTL
        }
    if recordType == 'MX':
        values = recordValue.split()
        requestParams['priority'] = values[0]
        requestParams['target'] = values[1]
    elif recordType == 'SRV':
        values = recordValue.split()
        requestParams['priority'] = values[0]
        requestParams['weight'] = values[1]
        requestParams['port'] = values[2]
        requestParams['target'] = values[3]
    elif recordType == 'TXT':
        if recordValue.startswith('"') and recordValue.endswith('"'):
            recordValue = recordValue[1:-1]
        requestParams['target'] = recordValue
    else:
        requestParams['target'] = recordValue
    recordResponse = execute_linode_request(requestParams)
    recordJson = json.loads(recordResponse)
    if DEBUG_LINODE: print(recordJson)
        
#
# Sanity check settings
#
def check_settings():
    if not LINODE_API_KEY: exit("No Linode API key defined")
    if not AWS_ACCESS_KEY: exit("No AWS access key defined")
    if not AWS_SECRET_KEY: exit("No AWS secret key defined")
    if not HOSTMASTER_EMAIL: exit("No hostmaster email address defined")
    if IMPORT_ZONES:
        print("Warning: IMPORT_ZONES is set, only the following zones will be migrated:");
        for zone in IMPORT_ZONES:
            print("\t{0}".format(zone))

# main
#
if __name__ == "__main__":
    check_settings()
    begin_zone_migration()

