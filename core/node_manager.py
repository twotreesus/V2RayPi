# encoding: utf-8
"""
File:       node_manager
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:57
Desc:
"""

from typing import List
from typing import Dict
from datetime import datetime
import time
import json
import requests
import base64
from tcp_latency import measure_latency
from concurrent import futures
from .keys import Keyword as K
from .node import Node
from .base_data_item import BaseDataItem

class NodeGroup:
    def __init__(self):
        self.subscribe: str = ''
        self.nodes: List[Node] = []

class NodeManager(BaseDataItem):
    def __init__(self):
        self.last_subscribe = ''
        self.subscribes: Dict= {}
        self.manual_nodes:List[Node] = []

    def filename(self):
        return 'config/nodes.json'

    def update_group(self, group: NodeGroup):
        url = group.subscribe
        r = requests.get(url)
        list = r.text
        list = base64.b64decode(list).decode('utf8')

        group.nodes.clear()
        for line in list.splitlines():
            if line.startswith(K.vmess_scheme):
                line = line[len(K.vmess_scheme):]
                line = base64.b64decode(line).decode('utf8')
                data = json.loads(line)
                node = Node().load_data(data)
                group.nodes.append(node)

    def update(self, url):
        group = self.subscribes[url]
        self.update_group(group)
        self.save()

    def update_all(self):
        for url in self.subscribes.keys():
            group = self.subscribes[url]
            self.update_group(group)

        self.refresh_update_time()
        self.save()

    def add_subscribe(self, url):
        group = NodeGroup()
        group.subscribe = url
        self.update_group(group)
        self.subscribes[url] = group

        self.refresh_update_time()
        self.save()

    def remove_subscribe(self, url):
        self.subscribes.pop(url)
        self.save()

    def delete_node(self, url, index):
        if url != K.manual:
            group = self.subscribes[url]
            group.nodes.pop(index)
        else:
            self.manual_nodes.pop(index)
        self.save()

    def add_manual_node(self, url):
        if url.startswith(K.vmess_scheme):
            line = url[len(K.vmess_scheme):]
            line = base64.b64decode(line).decode('utf8')
            data = json.loads(line)
            node = Node().load_data(data)
            self.manual_nodes.append(node)
            self.save()

    def find_node(self, url:str, index:int) -> Node:
        node = None
        if url == K.manual:
            node = self.manual_nodes[index]
        else:
            node = self.subscribes[url].nodes[index]
        return node

    def find_node_index(self, url:str, node_ps:str):
        node_list = None
        if url == K.manual:
            node_list = self.manual_nodes
        else:
            node_list = self.subscribes[url].nodes
        for node in node_list:
            if node.ps == node_ps:
                return node_list.index(node)

        return -1

    def all_nodes(self) ->list :
        nodes = []
        for url in self.subscribes.keys():
            group = self.subscribes[url]
            nodes.extend(group.nodes)
        nodes.extend(self.manual_nodes)
        return nodes

    def refresh_update_time(self):
        self.last_subscribe = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')

    def ping_test_all(self) -> list :
        results = []

        for url in self.subscribes.keys():
            group: NodeGroup = self.subscribes[url]
            if not len(group.nodes):
                continue

            node_results = self.ping_test_group(group.nodes)
            group_result = {
                K.subscribe : url,
                K.nodes : node_results
            }

            results.append(group_result)

        if len(self.manual_nodes):
            manual_nodes = self.ping_test_group(self.manual_nodes)
            manual_result = {
                K.subscribe: K.manual,
                K.nodes: manual_nodes
            }
            results.append(manual_result)

        return results

    def ping_test_group(self, nodes: List[Node]) -> dict:
        def ping(host, port):
            delay = measure_latency(host, port, 1)[0]
            return delay

        with futures.ThreadPoolExecutor(max_workers=len(nodes)) as executor:
            futures_to_hosts = {}
            for node in nodes:
                future = executor.submit(ping, node.add, node.port)
                futures_to_hosts[future] = node.ps
            futures.wait(futures_to_hosts.keys())

            node_results = {}
            for future in futures_to_hosts.keys():
                delay = future.result()
                if delay == None:
                    delay = -1
                node_results[futures_to_hosts[future]] = int(delay)

            return node_results