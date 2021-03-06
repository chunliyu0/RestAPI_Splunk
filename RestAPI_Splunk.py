################################################################################
# RestAPI_Splunk.py  -  retrieve hadoop log statistics from Splunk             #
# ver 1.0                                                                      #
# Language:    Python                                                          #
# Platform:    Python 2.6.6                                                    #
#              [GCC 4.4.7 20120313 (Red Hat 4.4.7-1)] on linux2                #
# Application: Splunk log statistics information Retrieval                     #                                                 #
################################################################################

import urllib
import urllib2
import json
import csv
import getpass
import re
import sys
import os
import time
import subprocess
from xml.dom import minidom
from optparse import OptionParser
from xml.etree import cElementTree

def main():
   
    # process the command options
    parser = OptionParser(usage='usage: %prog [options] arg1 arg2')
    parser.add_option('-f', '--file', type='string', dest='filename',
                      help="write report to FILE, if no filename is specified, it will print to the screen", metavar="FILE")
    parser.add_option("-H", '--host', dest='host', default='default is our own credential')
    parser.add_option("-U", '--user', dest='username')
    parser.add_option('--passfile', dest='passfile')
    parser.add_option("--proxy", dest="baseproxy")
    parser.add_option("--url", dest="baseurl")
    parser.add_option("--query", dest="query", default='index=hadoop-audit-logs sourcetype=queue-stats | search earliest_time=-1d', 
                      help='default: index=hadoop-audit-logs sourcetype=queue-stats | earliest=-1d')    
    
    (opts, args) = parser.parse_args()
    
    # get the username either from user input or by default
    if opts.username is None:
        username = getpass.getuser()
    else:
        username = opts.username

    if opts.passfile is None:
        print "password file in hdfs is required"
        sys.exit(1)

    # read the password from a file in hdfs
    try:
        cat = subprocess.Popen(["hadoop", "fs", "-cat", opts.passfile], stdout=subprocess.PIPE)
    except: 
      print "unable to read passfile from hdfs location: " + sys.exc_info()[0]
      sys.exit(1)

    password = cat.stdout.readline().strip()

    # install proxy
    #installProxy(username, password, opts.baseproxy)

    # auth login and get the session key
    session_key = authLogin(username, password, opts.baseurl)
    
    # process the search job based on the session key generated above
    doSearch(opts.query, opts.baseurl, session_key, username, password, opts.filename)

# Install proxy    
def installProxy(username, password, baseproxy):
    baseproxy = username + ':' + password + '@' + baseproxy
    try:
        proxy = urllib2.ProxyHandler({'http': baseproxy, 'https': baseproxy})
        opener = urllib2.build_opener(proxy)
        urllib2.install_opener(opener)
        print "==> proxy is installed successfully"
    except urllib2.HTTPError as e:
        print e.code
        print "proxy installation failed"
    except urllib2.URLError as e:
        print e.reason
        print "proxy installation failed"
    except:
        sys.exit(0)    

# Login Splunk REST API and get a session key
def authLogin(username, password, baseurl):
    login_url = baseurl + '/services/auth/login'
    
    try:
        auth_req = urllib2.Request(login_url, data = urllib.urlencode({'username':username, 'password':password}))
        server_content = urllib2.urlopen(auth_req)
    except urllib2.URLError as e:
        print e.reason
        raise
    
    try:
        session_key = minidom.parseString(server_content.read()).getElementsByTagName('sessionKey')[0].childNodes[0].nodeValue
        print "==> session key %s is retrieved successfully " % session_key
    except IndexError:
        print "failed to obtain the session key"
        raise

    return session_key

# Create a search job and write the search result to the specified file
def doSearch(query, baseurl, session_key, username, password, outputFile):
    
    # standardize the query
    if not query.startswith('search'):
        query = '{0} {1}'.format('search', query)

    search_url = baseurl + '/services/search/jobs'

    headers = {'Authorization': 'Splunk %s' % session_key}
    data = urllib.urlencode({'search': query})
    
    try:
        search_req = urllib2.Request(search_url, headers=headers, data=data)
        connection = urllib2.urlopen(search_req)
    except urllib2.HTTPError as e:
        print "the server could not fulfill the request"
        print e.code
        connection = e
        raise
    except urllib2.URLError as e:
        print "we failed to reach a server"
        print e.reason
        connection = e
        raise
    
    if connection.code == 201:
        data = connection.read()
    
    xml = cElementTree.fromstring(data)
    for line in xml.getiterator('sid'):
        sid = line.text
    
    print "==> sid %s is retrieved successfully " % sid
    #connection.close()
        
    checkStatus(baseurl, session_key, sid)
    getResult(baseurl, session_key, sid, outputFile)


# Check the search status
def checkStatus(baseurl, session_key, sid):
    services_search_status_str = '/services/search/jobs/%s/' % sid
    status_url = baseurl + services_search_status_str
    headers = {'Authorization': 'Splunk %s' % session_key}

    # check if the isDone status is 1, if so, continue to retrieve the final result
    while True:
        try:
            status_req = urllib2.Request(status_url, headers=headers)
            data = urllib2.urlopen(status_req)
        except urllib2.HTTPError as e:
            print "the server could not fulfill the request"
            print e.code
        except urllib2.URLError as e:
            print "we failed to reach a server"
            print e.reason

        # get the search job related information including the isDone status (0|1)
        try:
            key_list = minidom.parseString(data.read()).getElementsByTagName('s:key')
        except xml.parsers.expat.ExpatError, e:
            return str(e)
        
        for key in key_list :
            name = key.attributes['name'].value
            if(name == 'isDone'):
                status = key.firstChild.nodeValue
                break

        # jump out of the status checking loop
        if(status == '1'): 
            break;

    print "==> the job is done, status = %s" % status

# Get the search result
def getResult(baseurl, session_key, sid, outputFile):
    services_search_result_str = '/services/search/jobs/%s/results?output_mode=json&count=0' % sid
    result_url = baseurl + services_search_result_str
    headers = {'Authorization': 'Splunk %s' % session_key}

    try:
        result_req = urllib2.Request(result_url, headers=headers)
        data = urllib2.urlopen(result_req)
    except urllib2.HTTPError as e:
        print "the server could not fulfill the request"
        print e.code
    except urllib2.URLError as e:
        print "we failed to reach a server"
        print e.reason

    try:
        res = json.load(data)['results']
    except ValueError, e:
        print "json data is not loaded properly"
    else:
        pass

    try:
        if outputFile is None:
            csvfile = sys.stdout
        else:
            csvfile = open(outputFile, 'w')

        fieldnames = ['timestamp', 'queueName', 'capacity', 'usedCapacity', 'maxCapacity', 'absoluteCapacity', 'absoluteMaxCapacity', 'absoluteUsedCapacity', 'numApplications'] #csv title
        writer = csv.writer(csvfile, delimiter=',')
        writer.writerow(fieldnames)

        # extract the specified columns
        for item in res:
            raw = item['_raw'].strip()
            cols = raw.split(' ')
            row = cols[0] + ' ' + '.'.join(cols[1].split(',')) # time
            for col in cols[2:]:
                row = row + ',' + col.split('=')[1]
            #for queuename=root formatting, missing fields starting at "absoluteCapacity..." load them as null  
            if cols[2].split('=')[1] == 'root':
                row = row + ',,,,'
            writer.writerow(row.split(','))
        print "The search is completed successfully, check the result please!"
    except IOError:
        sys.exit(0)

if __name__ == "__main__":
    main()
