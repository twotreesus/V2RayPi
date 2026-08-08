# encoding: utf-8
"""
File:       node_manager
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:57
Desc:
"""

from typing import List, Optional
from datetime import datetime
import copy
import time
import requests
import yaml
from urllib.parse import urlparse
from .keys import Keyword as K
from .node import Node
from .mihomo_config import SUPPORTED_PROXY_TYPES
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

    def load(self):
        manager = super().load()
        manager._drop_nodes_without_clash_payload()
        return manager

    def _drop_nodes_without_clash_payload(self):
        """Discard nodes saved before the move to mihomo.

        Those entries carry the old per-protocol fields but no Clash payload, so
        they would still be listed and look applicable while producing a config
        with no outbound.  Dropping them makes it obvious that the subscription
        has to be added again.
        """
        dropped = 0
        for group in self.subscribes.values():
            kept = [node for node in group.nodes if getattr(node, 'clash', None)]
            dropped += len(group.nodes) - len(kept)
            group.nodes = kept
        kept_manual = [node for node in self.manual_nodes if getattr(node, 'clash', None)]
        dropped += len(self.manual_nodes) - len(kept_manual)
        self.manual_nodes = kept_manual
        if dropped:
            print('Dropped {0} node(s) saved by an older V2RayPi version, '
                  'please update the subscriptions again'.format(dropped))

    def _proxy_to_node(self, proxy: dict) -> Optional[Node]:
        if not isinstance(proxy, dict):
            return None
        if proxy.get('type') not in SUPPORTED_PROXY_TYPES:
            return None
        if not proxy.get('name') or not proxy.get('server'):
            return None
        return Node.from_clash(proxy)

    def update_group(self, group: NodeGroup):
        url = group.subscribe
        r = requests.get(url, headers={'User-Agent': K.subscribe_user_agent})

        try:
            clash = yaml.safe_load(r.text)
        except Exception as e:
            print('Subscription {0} is not valid YAML: {1}'.format(url, e))
            return
        if not isinstance(clash, dict) or 'proxies' not in clash:
            print('Subscription {0} is not a Clash configuration, no proxies found'.format(url))
            return

        group.nodes.clear()
        skipped = 0
        for proxy in (clash.get('proxies') or []):
            node = self._proxy_to_node(proxy)
            if node:
                group.nodes.append(node)
            else:
                skipped += 1
        if skipped:
            # Only the selected node is written into the mihomo config, but an
            # unsupported entry would still break it once applied.
            print('Subscription {0}: skipped {1} unsupported node(s)'.format(url, skipped))

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

    def all_nodes(self) -> list:
        nodes = []
        for url in self.subscribes.keys():
            group = self.subscribes[url]
            nodes.extend(group.nodes)
        nodes.extend(self.manual_nodes)
        return nodes

    def subscribe_hosts(self) -> list:
        hosts = []
        for url in self.subscribes.keys():
            host = urlparse(url).hostname
            if host:
                hosts.append(host)
        return hosts

    def refresh_update_time(self):
        self.last_subscribe = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
