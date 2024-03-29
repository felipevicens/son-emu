__author__ = 'Administrator'

import urllib2
import logging
from mininet.node import  OVSSwitch
import ast
import time
from prometheus_client import start_http_server, Summary, Histogram, Gauge, Counter, REGISTRY, CollectorRegistry, \
    pushadd_to_gateway, push_to_gateway, delete_from_gateway
import threading
from subprocess import Popen, PIPE
import os

import paramiko
import gevent

logging.basicConfig(level=logging.INFO)

"""
class to read openflow stats from the Ryu controller of the DCNetwork
"""

class DCNetworkMonitor():
    def __init__(self, net):
        self.net = net

        prometheus_ip = '127.0.0.1'
        prometheus_port = '9090'
        self.prometheus_REST_api = 'http://{0}:{1}'.format(prometheus_ip, prometheus_port)



        # helper variables to calculate the metrics
        self.pushgateway = 'localhost:9091'
        # Start up the server to expose the metrics to Prometheus.
        #start_http_server(8000)
        # supported Prometheus metrics
        self.registry = CollectorRegistry()
        self.prom_tx_packet_count = Gauge('sonemu_tx_count_packets', 'Total number of packets sent',
                                          ['vnf_name', 'vnf_interface', 'flow_id'], registry=self.registry)
        self.prom_rx_packet_count = Gauge('sonemu_rx_count_packets', 'Total number of packets received',
                                          ['vnf_name', 'vnf_interface', 'flow_id'], registry=self.registry)
        self.prom_tx_byte_count = Gauge('sonemu_tx_count_bytes', 'Total number of bytes sent',
                                        ['vnf_name', 'vnf_interface', 'flow_id'], registry=self.registry)
        self.prom_rx_byte_count = Gauge('sonemu_rx_count_bytes', 'Total number of bytes received',
                                        ['vnf_name', 'vnf_interface', 'flow_id'], registry=self.registry)

        self.prom_metrics={'tx_packets':self.prom_tx_packet_count, 'rx_packets':self.prom_rx_packet_count,
                           'tx_bytes':self.prom_tx_byte_count,'rx_bytes':self.prom_rx_byte_count}

        # list of installed metrics to monitor
        # each entry can contain this data
        '''
        {
        switch_dpid = 0
        vnf_name = None
        vnf_interface = None
        previous_measurement = 0
        previous_monitor_time = 0
        metric_key = None
        mon_port = None
        }
        '''
        self.monitor_lock = threading.Lock()
        self.monitor_flow_lock = threading.Lock()
        self.network_metrics = []
        self.flow_metrics = []

        # start monitoring thread
        self.start_monitoring = True
        self.monitor_thread = threading.Thread(target=self.get_network_metrics)
        self.monitor_thread.start()

        self.monitor_flow_thread = threading.Thread(target=self.get_flow_metrics)
        self.monitor_flow_thread.start()

        # helper tools
        #self.pushgateway_process = self.start_PushGateway()
        #self.prometheus_process = self.start_Prometheus()
        self.cadvisor_process = self.start_cadvisor()

    # first set some parameters, before measurement can start
    def setup_flow(self, vnf_name, vnf_interface=None, metric='tx_packets', cookie=0):

        flow_metric = {}

        # check if port is specified (vnf:port)
        if vnf_interface is None:
            # take first interface by default
            connected_sw = self.net.DCNetwork_graph.neighbors(vnf_name)[0]
            link_dict = self.net.DCNetwork_graph[vnf_name][connected_sw]
            vnf_interface = link_dict[0]['src_port_id']

        flow_metric['vnf_name'] = vnf_name
        flow_metric['vnf_interface'] = vnf_interface

        vnf_switch = None
        for connected_sw in self.net.DCNetwork_graph.neighbors(vnf_name):
            link_dict = self.net.DCNetwork_graph[vnf_name][connected_sw]
            for link in link_dict:
                # logging.info("{0},{1}".format(link_dict[link],vnf_interface))
                if link_dict[link]['src_port_id'] == vnf_interface:
                    # found the right link and connected switch
                    # logging.info("{0},{1}".format(link_dict[link]['src_port_id'], vnf_source_interface))
                    vnf_switch = connected_sw
                    flow_metric['mon_port'] = link_dict[link]['dst_port_nr']
                    break

        if not vnf_switch:
            logging.exception("vnf switch of {0}:{1} not found!".format(vnf_name, vnf_interface))
            return "vnf switch of {0}:{1} not found!".format(vnf_name, vnf_interface)

        try:
            # default port direction to monitor
            if metric is None:
                metric = 'tx_packets'

            next_node = self.net.getNodeByName(vnf_switch)

            if not isinstance(next_node, OVSSwitch):
                logging.info("vnf: {0} is not connected to switch".format(vnf_name))
                return

            flow_metric['previous_measurement'] = 0
            flow_metric['previous_monitor_time'] = 0

            flow_metric['switch_dpid'] = int(str(next_node.dpid), 16)
            flow_metric['metric_key'] = metric
            flow_metric['cookie'] = cookie

            self.monitor_flow_lock.acquire()
            self.flow_metrics.append(flow_metric)
            self.monitor_flow_lock.release()

            logging.info('Started monitoring flow:{3} {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric, cookie))
            return 'Started monitoring flow:{3} {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric, cookie)

        except Exception as ex:
            logging.exception("setup_metric error.")
            return ex.message

    def stop_flow(self, vnf_name, vnf_interface=None, metric=None, cookie=0):
        for flow_dict in self.flow_metrics:
            if flow_dict['vnf_name'] == vnf_name and flow_dict['vnf_interface'] == vnf_interface \
                    and flow_dict['metric_key'] == metric and flow_dict['cookie'] == cookie:

                self.monitor_flow_lock.acquire()

                self.flow_metrics.remove(flow_dict)

                for collector in self.registry._collectors:
                    if (vnf_name, vnf_interface, cookie) in collector._metrics:
                        #logging.info('2 name:{0} labels:{1} metrics:{2}'.format(collector._name, collector._labelnames,
                        #                                                        collector._metrics))
                        collector.remove(vnf_name, vnf_interface, cookie)

                delete_from_gateway(self.pushgateway, job='sonemu-SDNcontroller')

                self.monitor_flow_lock.release()

                logging.info('Stopped monitoring flow {3}: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric, cookie))
                return 'Stopped monitoring flow {3}: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric, cookie)


    # first set some parameters, before measurement can start
    def setup_metric(self, vnf_name, vnf_interface=None, metric='tx_packets'):

        network_metric = {}

        # check if port is specified (vnf:port)
        if vnf_interface is None:
            # take first interface by default
            connected_sw = self.net.DCNetwork_graph.neighbors(vnf_name)[0]
            link_dict = self.net.DCNetwork_graph[vnf_name][connected_sw]
            vnf_interface = link_dict[0]['src_port_id']

        network_metric['vnf_name'] = vnf_name
        network_metric['vnf_interface'] = vnf_interface

        for connected_sw in self.net.DCNetwork_graph.neighbors(vnf_name):
            link_dict = self.net.DCNetwork_graph[vnf_name][connected_sw]
            for link in link_dict:
                # logging.info("{0},{1}".format(link_dict[link],vnf_interface))
                if link_dict[link]['src_port_id'] == vnf_interface:
                    # found the right link and connected switch
                    # logging.info("{0},{1}".format(link_dict[link]['src_port_id'], vnf_source_interface))
                    network_metric['mon_port'] = link_dict[link]['dst_port_nr']
                    break

        if 'mon_port' not in network_metric:
            logging.exception("vnf interface {0}:{1} not found!".format(vnf_name,vnf_interface))
            return "vnf interface {0}:{1} not found!".format(vnf_name,vnf_interface)

        try:
            # default port direction to monitor
            if metric is None:
                metric = 'tx_packets'

            vnf_switch = self.net.DCNetwork_graph.neighbors(str(vnf_name))

            if len(vnf_switch) > 1:
                logging.info("vnf: {0} has multiple ports".format(vnf_name))
                return
            elif len(vnf_switch) == 0:
                logging.info("vnf: {0} is not connected".format(vnf_name))
                return
            else:
                vnf_switch = vnf_switch[0]
            next_node = self.net.getNodeByName(vnf_switch)

            if not isinstance(next_node, OVSSwitch):
                logging.info("vnf: {0} is not connected to switch".format(vnf_name))
                return

            network_metric['previous_measurement'] = 0
            network_metric['previous_monitor_time'] = 0


            network_metric['switch_dpid'] = int(str(next_node.dpid), 16)
            network_metric['metric_key'] = metric

            self.monitor_lock.acquire()

            self.network_metrics.append(network_metric)
            self.monitor_lock.release()


            logging.info('Started monitoring: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric))
            return 'Started monitoring: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric)

        except Exception as ex:
            logging.exception("setup_metric error.")
            return ex.message

    def stop_metric(self, vnf_name, vnf_interface=None, metric=None):

        for metric_dict in self.network_metrics:
            #logging.info('start Stopped monitoring: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric_dict))
            if metric_dict['vnf_name'] == vnf_name and metric_dict['vnf_interface'] == vnf_interface \
                    and metric_dict['metric_key'] == metric:

                self.monitor_lock.acquire()

                self.network_metrics.remove(metric_dict)

                #this removes the complete metric, all labels...
                #REGISTRY.unregister(self.prom_metrics[metric_dict['metric_key']])
                #self.registry.unregister(self.prom_metrics[metric_dict['metric_key']])

                for collector in self.registry._collectors :
                    #logging.info('name:{0} labels:{1} metrics:{2}'.format(collector._name, collector._labelnames, collector._metrics))
                    """
                    INFO:root:name:sonemu_rx_count_packets
                    labels:('vnf_name', 'vnf_interface')
                    metrics:{(u'tsrc', u'output'): < prometheus_client.core.Gauge
                    object
                    at
                    0x7f353447fd10 >}
                    """
                    logging.info('{0}'.format(collector._metrics.values()))
                    #if self.prom_metrics[metric_dict['metric_key']]
                    if (vnf_name, vnf_interface, 'None') in collector._metrics:
                        logging.info('2 name:{0} labels:{1} metrics:{2}'.format(collector._name, collector._labelnames,
                                                                              collector._metrics))
                        #collector._metrics = {}
                        collector.remove(vnf_name, vnf_interface, 'None')

                # set values to NaN, prometheus api currently does not support removal of metrics
                #self.prom_metrics[metric_dict['metric_key']].labels(vnf_name, vnf_interface).set(float('nan'))

                # this removes the complete metric, all labels...
                # 1 single monitor job for all metrics of the SDN controller
                # we can only  remove from the pushgateway grouping keys(labels) which we have defined for the add_to_pushgateway
                # we can not specify labels from the metrics to be removed
                # if we need to remove the metrics seperatelty, we need to give them a separate grouping key, and probably a diffferent registry also
                delete_from_gateway(self.pushgateway, job='sonemu-SDNcontroller')

                self.monitor_lock.release()

                logging.info('Stopped monitoring: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric))
                return 'Stopped monitoring: {2} on {0}:{1}'.format(vnf_name, vnf_interface, metric)

            # delete everything from this vnf
            elif metric_dict['vnf_name'] == vnf_name and vnf_interface is None and metric is None:
                self.monitor_lock.acquire()
                self.network_metrics.remove(metric_dict)
                for collector in self.registry._collectors:
                    collector_dict = collector._metrics.copy()
                    for name, interface, id in collector_dict:
                        if name == vnf_name:
                            logging.info('3 name:{0} labels:{1} metrics:{2}'.format(collector._name, collector._labelnames,
                                                                           collector._metrics))
                            collector.remove(name, interface, 'None')

                delete_from_gateway(self.pushgateway, job='sonemu-SDNcontroller')
                self.monitor_lock.release()
                logging.info('Stopped monitoring vnf: {0}'.format(vnf_name))
                return 'Stopped monitoring: {0}'.format(vnf_name)


    # get all metrics defined in the list and export it to Prometheus
    def get_flow_metrics(self):
        while self.start_monitoring:

            self.monitor_flow_lock.acquire()

            for flow_dict in self.flow_metrics:
                data = {}

                data['cookie'] = flow_dict['cookie']

                if 'tx' in flow_dict['metric_key']:
                    data['match'] = {'in_port':flow_dict['mon_port']}
                elif 'rx' in flow_dict['metric_key']:
                    data['out_port'] = flow_dict['mon_port']


                # query Ryu
                ret = self.net.ryu_REST('stats/flow', dpid=flow_dict['switch_dpid'], data=data)
                flow_stat_dict = ast.literal_eval(ret)

                #logging.info('received flow stat:{0} '.format(flow_stat_dict))
                self.set_flow_metric(flow_dict, flow_stat_dict)

            self.monitor_flow_lock.release()
            time.sleep(1)

    def get_network_metrics(self):
        while self.start_monitoring:

            self.monitor_lock.acquire()

            # group metrics by dpid to optimize the rest api calls
            dpid_list = [metric_dict['switch_dpid'] for metric_dict in self.network_metrics]
            dpid_set = set(dpid_list)

            for dpid in dpid_set:

                # query Ryu
                ret = self.net.ryu_REST('stats/port', dpid=dpid)
                port_stat_dict = ast.literal_eval(ret)

                metric_list = [metric_dict for metric_dict in self.network_metrics
                               if int(metric_dict['switch_dpid'])==int(dpid)]
                #logging.info('1set prom packets:{0} '.format(self.network_metrics))
                for metric_dict in metric_list:
                    self.set_network_metric(metric_dict, port_stat_dict)

            self.monitor_lock.release()
            time.sleep(1)

    # add metric to the list to export to Prometheus, parse the Ryu port-stats reply
    def set_network_metric(self, metric_dict, port_stat_dict):
        # vnf tx is the datacenter switch rx and vice-versa
        metric_key = self.switch_tx_rx(metric_dict['metric_key'])
        switch_dpid = metric_dict['switch_dpid']
        vnf_name = metric_dict['vnf_name']
        vnf_interface = metric_dict['vnf_interface']
        previous_measurement = metric_dict['previous_measurement']
        previous_monitor_time = metric_dict['previous_monitor_time']
        mon_port = metric_dict['mon_port']

        for port_stat in port_stat_dict[str(switch_dpid)]:
            if int(port_stat['port_no']) == int(mon_port):
                port_uptime = port_stat['duration_sec'] + port_stat['duration_nsec'] * 10 ** (-9)
                this_measurement = int(port_stat[metric_key])
                #logging.info('set prom packets:{0} {1}:{2}'.format(this_measurement, vnf_name, vnf_interface))

                # set prometheus metric
                self.prom_metrics[metric_dict['metric_key']].\
                    labels({'vnf_name': vnf_name, 'vnf_interface': vnf_interface, 'flow_id': None}).\
                    set(this_measurement)
                #push_to_gateway(self.pushgateway, job='SDNcontroller',
                #                grouping_key={'metric':metric_dict['metric_key']}, registry=self.registry)

                # 1 single monitor job for all metrics of the SDN controller
                pushadd_to_gateway(self.pushgateway, job='sonemu-SDNcontroller', registry=self.registry)

                if previous_monitor_time <= 0 or previous_monitor_time >= port_uptime:
                    metric_dict['previous_measurement'] = int(port_stat[metric_key])
                    metric_dict['previous_monitor_time'] = port_uptime
                    # do first measurement
                    #logging.info('first measurement')
                    time.sleep(1)
                    self.monitor_lock.release()

                    metric_rate = self.get_network_metrics()
                    return metric_rate

                else:
                    time_delta = (port_uptime - metric_dict['previous_monitor_time'])
                    metric_rate = (this_measurement - metric_dict['previous_measurement']) / float(time_delta)
                    #logging.info('metric: {0} rate:{1}'.format(metric_dict['metric_key'], metric_rate))

                metric_dict['previous_measurement'] = this_measurement
                metric_dict['previous_monitor_time'] = port_uptime
                return metric_rate

        logging.exception('metric {0} not found on {1}:{2}'.format(metric_key, vnf_name, vnf_interface))
        return 'metric {0} not found on {1}:{2}'.format(metric_key, vnf_name, vnf_interface)

    def set_flow_metric(self, metric_dict, flow_stat_dict):
        # vnf tx is the datacenter switch rx and vice-versa
        #metric_key = self.switch_tx_rx(metric_dict['metric_key'])
        metric_key = metric_dict['metric_key']
        switch_dpid = metric_dict['switch_dpid']
        vnf_name = metric_dict['vnf_name']
        vnf_interface = metric_dict['vnf_interface']
        previous_measurement = metric_dict['previous_measurement']
        previous_monitor_time = metric_dict['previous_monitor_time']
        cookie = metric_dict['cookie']

        # TODO aggregate all found flow stats
        flow_stat = flow_stat_dict[str(switch_dpid)][0]
        if 'bytes' in  metric_key:
            counter = flow_stat['byte_count']
        elif 'packet' in metric_key:
            counter = flow_stat['packet_count']

        flow_uptime = flow_stat['duration_sec'] + flow_stat['duration_nsec'] * 10 ** (-9)

        self.prom_metrics[metric_dict['metric_key']]. \
            labels({'vnf_name': vnf_name, 'vnf_interface': vnf_interface, 'flow_id': cookie}). \
            set(counter)
        pushadd_to_gateway(self.pushgateway, job='sonemu-SDNcontroller', registry=self.registry)

        #logging.exception('metric {0} not found on {1}:{2}'.format(metric_key, vnf_name, vnf_interface))
        #return 'metric {0} not found on {1}:{2}'.format(metric_key, vnf_name, vnf_interface)

    def query_Prometheus(self, query):
        '''
        escaped_chars='{}[]'
        for old in escaped_chars:
            new = '\{0}'.format(old)
            query = query.replace(old, new)
        '''
        url = self.prometheus_REST_api + '/' + 'api/v1/query?query=' + query
        #logging.info('query:{0}'.format(url))
        req = urllib2.Request(url)
        ret = urllib2.urlopen(req).read()
        ret = ast.literal_eval(ret)
        if ret['status'] == 'success':
            #logging.info('return:{0}'.format(ret))
            try:
                ret = ret['data']['result'][0]['value']
            except:
                ret = None
        else:
            ret = None
        return ret

    def start_Prometheus(self, port=9090):
        # prometheus.yml configuration file is located in the same directory as this file
        cmd = ["docker",
               "run",
               "--rm",
               "-p", "{0}:9090".format(port),
               "-v", "{0}/prometheus.yml:/etc/prometheus/prometheus.yml".format(os.path.dirname(os.path.abspath(__file__))),
               "-v", "{0}/profile.rules:/etc/prometheus/profile.rules".format(os.path.dirname(os.path.abspath(__file__))),
               "--name", "prometheus",
               "prom/prometheus"
               ]
        logging.info('Start Prometheus container {0}'.format(cmd))
        return Popen(cmd)

    def start_PushGateway(self, port=9091):
        cmd = ["docker",
               "run",
               "-d",
               "-p", "{0}:9091".format(port),
               "--name", "pushgateway",
               "prom/pushgateway"
               ]

        logging.info('Start Prometheus Push Gateway container {0}'.format(cmd))
        return Popen(cmd)

    def start_cadvisor(self, port=8090):
        cmd = ["docker",
               "run",
               "--rm",
               "--volume=/:/rootfs:ro",
               "--volume=/var/run:/var/run:rw",
               "--volume=/sys:/sys:ro",
               "--volume=/var/lib/docker/:/var/lib/docker:ro",
               "--publish={0}:8080".format(port),
               "--name=cadvisor",
               "google/cadvisor:latest"
               ]
        logging.info('Start cAdvisor container {0}'.format(cmd))
        return Popen(cmd)

    def stop(self):
        # stop the monitoring thread
        self.start_monitoring = False
        self.monitor_thread.join()
        self.monitor_flow_thread.join()

        '''
        if self.prometheus_process is not None:
            logging.info('stopping prometheus container')
            self.prometheus_process.terminate()
            self.prometheus_process.kill()
            self._stop_container('prometheus')

        if self.pushgateway_process is not None:
            logging.info('stopping pushgateway container')
            self.pushgateway_process.terminate()
            self.pushgateway_process.kill()
            self._stop_container('pushgateway')
        '''

        if self.cadvisor_process is not None:
            logging.info('stopping cadvisor container')
            self.cadvisor_process.terminate()
            self.cadvisor_process.kill()
            self._stop_container('cadvisor')

    def switch_tx_rx(self,metric=''):
        # when monitoring vnfs, the tx of the datacenter switch is actually the rx of the vnf
        # so we need to change the metric name to be consistent with the vnf rx or tx
        if 'tx' in metric:
            metric = metric.replace('tx','rx')
        elif 'rx' in metric:
            metric = metric.replace('rx','tx')

        return metric

    def _stop_container(self, name):
        cmd = ["docker",
               "stop",
               name]
        Popen(cmd).wait()

        cmd = ["docker",
               "rm",
               name]
        Popen(cmd).wait()

    def profile(self, mgmt_ip, rate, input_ip, vnf_uuid ):

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        #ssh.connect(mgmt_ip, username='steven', password='test')
        ssh.connect(mgmt_ip, username='root', password='root')

        iperf_cmd = 'iperf -c {0} -u -l18 -b{1}M -t1000 &'.format(input_ip, rate)
        if rate > 0:
            stdin, stdout, stderr = ssh.exec_command(iperf_cmd)

        start_time = time.time()
        query_cpu = '(sum(rate(container_cpu_usage_seconds_total{{id="/docker/{0}"}}[{1}s])))'.format(vnf_uuid, 1)
        while (time.time() - start_time) < 15:
            data = self.query_Prometheus(query_cpu)
            # logging.info('rate: {1} data:{0}'.format(data, rate))
            gevent.sleep(0)
            time.sleep(1)

        query_cpu2 = '(sum(rate(container_cpu_usage_seconds_total{{id="/docker/{0}"}}[{1}s])))'.format(vnf_uuid, 8)
        cpu_load = float(self.query_Prometheus(query_cpu2)[1])
        output = 'rate: {1}Mbps; cpu_load: {0}%'.format(round(cpu_load * 100, 2), rate)
        output_line = output
        logging.info(output_line)

        stop_iperf = 'pkill -9 iperf'
        stdin, stdout, stderr = ssh.exec_command(stop_iperf)

        return output_line

