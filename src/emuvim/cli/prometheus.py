"""
Prometheus API helper functions
(c) 2016 by Steven Van Rossem <steven.vanrossem@intec.ugent.be>
"""

#import urllib2
import requests
#import ast

# set this to localhost for now
# this is correct for son-emu started outside of a container or as a container with net=host
prometheus_ip = '127.0.0.1'
prometheus_port = '9090'
prometheus_REST_api = 'http://{0}:{1}'.format(prometheus_ip, prometheus_port)


def query_Prometheus(query):
    url = prometheus_REST_api + '/' + 'api/v1/query?query=' + query
    # logging.info('query:{0}'.format(url))
    #req = urllib2.Request(url)
    req = requests.get(url)
    #ret = urllib2.urlopen(req).read()
    #ret = ast.literal_eval(ret)
    ret = req.json()
    if ret['status'] == 'success':
        # logging.info('return:{0}'.format(ret))
        try:
            ret = ret['data']['result'][0]['value']
        except:
            ret = None
    else:
        ret = None
    return ret