# encoding: utf-8
"""
File:       node_manager
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:57
Desc:
"""

from typing import List, Dict, Optional
from datetime import datetime
import copy
import time
import json
import requests
import base64
import yaml
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
        self.subscribes: Dict = {}
        self.manual_nodes: List[Node] = []

    def filename(self):
        return 'config/nodes.json'

    def _parse_node_uri(self, line: str) -> Optional[Node]:
        if line.startswith(K.anytls_scheme):
            data = Node.anytls_uri_to_data(line)
            return Node().load_data(data) if data else None
        if line.startswith(K.vless_scheme):
            data = Node.vless_uri_to_data(line)
            return Node().load_data(data) if data else None
        if line.startswith(K.vmess_scheme):
            try:
                data = json.loads(base64.b64decode(line[len(K.vmess_scheme):]).decode('utf8'))
                data['protocol'] = 'vmess'
                return Node().load_data(data)
            except Exception:
                return None
        return None

    def _clash_proxy_to_node(self, proxy: dict) -> Optional[Node]:
        ptype = proxy.get('type', '')
        node = Node()
        node.ps = proxy.get('name', '')
        node.add = proxy.get('server', '')
        node.port = proxy.get('port', 0)

        if ptype == 'anytls':
            node.protocol = 'anytls'
            node.password = proxy.get('password', '')
            node.sni = proxy.get('sni', '') or node.add
            node.skip_cert_verify = proxy.get('skip-cert-verify', False)

        elif ptype == 'vmess':
            node.protocol = 'vmess'
            node.id = proxy.get('uuid', '')
            node.aid = proxy.get('alterId', 0)
            node.scy = proxy.get('cipher', 'auto')
            node.net = proxy.get('network', 'tcp')
            node.type = 'none'
            node.tls = 'tls' if proxy.get('tls') else None
            node.sni = proxy.get('servername', '') or node.add
            ws_opts = proxy.get('ws-opts', {})
            node.path = ws_opts.get('path', '')
            node.host = (ws_opts.get('headers') or {}).get('Host', '')

        elif ptype == 'vless':
            node.protocol = 'vless'
            node.id = proxy.get('uuid', '')
            node.net = proxy.get('network', 'tcp')
            node.type = 'none'
            node.path = ''
            node.flow = proxy.get('flow', None)
            node.fp = proxy.get('client-fingerprint', 'chrome')
            reality_opts = proxy.get('reality-opts', {})
            node.pbk = reality_opts.get('public-key', '')
            node.sid = reality_opts.get('short-id', '')
            if proxy.get('tls'):
                node.tls = 'reality' if node.pbk else 'tls'
            else:
                node.tls = None
            node.sni = proxy.get('servername', '') or node.add
            node.host = node.sni

        else:
            return None

        return node

    def _parse_clash_content(self, group: NodeGroup, content: str):
        try:
            clash = yaml.safe_load(content)
        except Exception:
            return
        proxies = clash.get('proxies') or []
        for proxy in proxies:
            node = self._clash_proxy_to_node(proxy)
            if node:
                group.nodes.append(node)

    def update_group(self, group: NodeGroup):
        url = group.subscribe
        r = requests.get(url, headers={'User-Agent': K.subscribe_user_agent})
        content = r.text

        group.nodes.clear()
        if 'proxies:' in content:
            self._parse_clash_content(group, content)
        else:
            try:
                decoded = base64.b64decode(content).decode('utf8')
            except Exception:
                return
            for line in decoded.splitlines():
                line = line.strip()
                if not line:
                    continue
                node = self._parse_node_uri(line)
                if node:
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
        node = self._parse_node_uri(url.strip())
        if node:
            self.manual_nodes.append(node)
            self.save()

    def favorite_node(self, url: str, index: int) -> bool:
        node = self.find_node(url, index)
        if any(n.ps == node.ps for n in self.manual_nodes):
            return False
        self.manual_nodes.append(copy.deepcopy(node))
        self.save()
        return True

    def find_node(self, url: str, index: int) -> Node:
        node = None
        if url == K.manual:
            node = self.manual_nodes[index]
        else:
            node = self.subscribes[url].nodes[index]
        return node

    def find_node_index(self, url: str, node_ps: str):
        node_list = None
        if url == K.manual:
            node_list = self.manual_nodes
        else:
            node_list = self.subscribes[url].nodes
        for node in node_list:
            if node.ps == node_ps:
                return node_list.index(node)

        return -1

    def all_nodes(self) -> list:
        nodes = []
        for url in self.subscribes.keys():
            group = self.subscribes[url]
            nodes.extend(group.nodes)
        nodes.extend(self.manual_nodes)
        return nodes

    def refresh_update_time(self):
        self.last_subscribe = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')

    def ping_test_all(self) -> list:
        results = []

        for url in self.subscribes.keys():
            group: NodeGroup = self.subscribes[url]
            if not len(group.nodes):
                continue

            node_results = self.ping_test_group(group.nodes)
            group_result = {
                K.subscribe: url,
                K.nodes: node_results
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
                if delay is None:
                    delay = -1
                node_results[futures_to_hosts[future]] = int(delay)

            return node_results
