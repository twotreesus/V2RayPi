# encoding: utf-8
"""
File:       node_manager
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:57
Desc:
"""

from typing import List, Optional
from datetime import datetime
import base64
import re
import time
import requests
import yaml
from urllib.parse import unquote, urlparse
from .keys import Keyword as K
from .node import Node
from .node_uri import parse_node_uri
from .mihomo_config import SUPPORTED_PROXY_TYPES
from .base_data_item import BaseDataItem

class NodeGroup:
    def __init__(self):
        self.subscribe: str = ''
        self.name: str = ''
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
        manager._drop_copied_favorites()
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
        kept_manual = [
            node for node in self.manual_nodes
            if getattr(node, 'clash', None) or self._is_subscription_favorite(node)
        ]
        dropped += len(self.manual_nodes) - len(kept_manual)
        self.manual_nodes = kept_manual
        if dropped:
            print('Dropped {0} node(s) saved by an older V2RayPi version, '
                  'please update the subscriptions again'.format(dropped))

    def _drop_copied_favorites(self):
        kept = []
        dropped = 0
        for node in self.manual_nodes:
            if self._is_subscription_favorite(node) and getattr(node, 'clash', None):
                dropped += 1
                continue
            kept.append(node)
        self.manual_nodes = kept
        if dropped:
            print('Cleared {0} favorite node(s) saved as copies by an older V2RayPi version'.format(
                dropped))

    def _proxy_to_node(self, proxy: dict) -> Optional[Node]:
        if not isinstance(proxy, dict):
            return None
        if proxy.get('type') not in SUPPORTED_PROXY_TYPES:
            return None
        if not proxy.get('name') or not proxy.get('server'):
            return None
        return Node.from_clash(proxy)

    def _decode_profile_title(self, value: str) -> str:
        value = (value or '').strip()
        if not value:
            return ''
        if value.lower().startswith('base64:'):
            raw = value.split(':', 1)[1]
            try:
                return base64.b64decode(raw).decode('utf-8', errors='replace').strip()
            except Exception:
                return ''
        return value

    def _filename_from_content_disposition(self, header: str) -> str:
        header = header or ''
        starred = re.search(
            r"filename\*\s*=\s*(?:UTF-8''|utf-8'')([^;]+)",
            header,
            re.I,
        )
        if starred:
            name = unquote(starred.group(1).strip().strip('"'))
        else:
            quoted = re.search(r'filename\s*=\s*"([^"]+)"', header, re.I)
            plain = re.search(r'filename\s*=\s*([^;]+)', header, re.I)
            name = (quoted or plain).group(1).strip().strip('"') if (quoted or plain) else ''
        name = re.sub(r'\.(ya?ml|txt|json)$', '', name, flags=re.I).strip()
        return name

    def _extract_subscribe_name(self, response, url: str) -> str:
        headers = getattr(response, 'headers', None) or {}
        title = self._decode_profile_title(
            headers.get('profile-title') or headers.get('Profile-Title') or '',
        )
        if title:
            return title
        filename = self._filename_from_content_disposition(
            headers.get('content-disposition') or headers.get('Content-Disposition') or '',
        )
        if filename:
            return filename
        host = urlparse(url).hostname or ''
        return host

    def update_group(self, group: NodeGroup, fill_name: bool = False):
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

        if fill_name and not (group.name or '').strip():
            name = self._extract_subscribe_name(r, url)
            if name:
                group.name = name
                print('Subscription {0}: using name {1}'.format(url, name))

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
        self._prune_missing_favorites(group)

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

    def add_subscribe(self, url, name: str = ''):
        group = NodeGroup()
        group.subscribe = url
        group.name = (name or '').strip()
        self.update_group(group, fill_name=True)
        self.subscribes[url] = group

        self.refresh_update_time()
        self.save()

    def rename_subscribe(self, url, name: str):
        name = (name or '').strip()
        if not name:
            raise ValueError('name is required')
        group = self.subscribes[url]
        group.name = name
        self.save()

    def remove_subscribe(self, url):
        self.subscribes.pop(url)
        self._drop_favorites_for_subscribe(url)
        self.save()

    def delete_node(self, url, index):
        if url != K.manual:
            group = self.subscribes[url]
            group.nodes.pop(index)
            self._prune_missing_favorites(group)
        else:
            self.manual_nodes.pop(index)
        self.save()

    def _airport_name(self, url: str) -> str:
        group = self.subscribes.get(url)
        if not group:
            return urlparse(url).hostname or ''
        return (group.name or '').strip() or (urlparse(url).hostname or '')

    def airport_name_for_node(self, node) -> str:
        airport = (getattr(node, 'airport', None) or '').strip()
        if airport:
            return airport
        url = getattr(node, 'subscribe', None) or ''
        if url:
            return self._airport_name(url)
        identity = (
            getattr(node, 'protocol', None),
            getattr(node, 'add', None),
            getattr(node, 'port', None),
            getattr(node, 'ps', None),
        )
        if not any(identity):
            return ''
        for group_url, group in self.subscribes.items():
            for candidate in group.nodes:
                if (
                    candidate.protocol,
                    candidate.add,
                    candidate.port,
                    candidate.ps,
                ) == identity:
                    return self._airport_name(group_url)
        return ''

    def _is_subscription_favorite(self, node: Node) -> bool:
        return bool((getattr(node, 'subscribe', None) or '').strip()
                    and (getattr(node, 'ps', None) or '').strip())

    def _subscription_node_by_name(self, group: NodeGroup, name: str) -> Optional[Node]:
        for candidate in group.nodes:
            if candidate.ps == name:
                return candidate
        return None

    def _prune_missing_favorites(self, group: NodeGroup):
        url = group.subscribe
        names = {node.ps for node in group.nodes}
        kept = []
        removed = []
        for node in self.manual_nodes:
            if (getattr(node, 'subscribe', None) or '') != url:
                kept.append(node)
                continue
            if node.ps in names:
                node.airport = (group.name or '').strip() or (urlparse(url).hostname or '')
                node.clash = {}
                node.add = None
                node.port = None
                node.protocol = None
                kept.append(node)
                continue
            removed.append(node.ps or '')
        self.manual_nodes = kept
        if removed:
            print('Subscription {0}: removed {1} favorite node(s) that no longer exist: {2}'.format(
                url, len(removed), ', '.join(removed)))

    def _drop_favorites_for_subscribe(self, url: str):
        kept = []
        removed = []
        for node in self.manual_nodes:
            if (getattr(node, 'subscribe', None) or '') == url:
                removed.append(node.ps or '')
                continue
            kept.append(node)
        self.manual_nodes = kept
        if removed:
            print('Subscription {0}: removed {1} favorite node(s) with the subscription: {2}'.format(
                url, len(removed), ', '.join(removed)))

    def resolve_manual_node(self, node: Node) -> Node:
        url = (getattr(node, 'subscribe', None) or '').strip()
        if not url:
            return node
        group = self.subscribes.get(url)
        if not group:
            return node
        source = self._subscription_node_by_name(group, node.ps)
        if not source:
            return node
        resolved = Node()
        resolved.clash = source.clash
        resolved.ps = source.ps
        resolved.add = source.add
        resolved.port = source.port
        resolved.protocol = source.protocol
        resolved.subscribe = url
        resolved.airport = self._airport_name(url)
        return resolved

    def resolved_manual_nodes(self) -> List[Node]:
        return [self.resolve_manual_node(node) for node in self.manual_nodes]

    def favorite_node(self, url: str, index: int) -> bool:
        node = self.find_node(url, index)
        if any(n.ps == node.ps for n in self.manual_nodes):
            return False
        reference = Node()
        reference.ps = node.ps
        reference.subscribe = url
        reference.airport = self._airport_name(url)
        self.manual_nodes.append(reference)
        self.save()
        return True

    def add_manual_node(self, uri: str) -> bool:
        node = Node.from_clash(parse_node_uri(uri))
        if any(existing.ps == node.ps for existing in self.manual_nodes):
            return False
        self.manual_nodes.append(node)
        self.save()
        return True

    def find_node(self, url: str, index: int) -> Node:
        if url == K.manual:
            return self.resolve_manual_node(self.manual_nodes[index])
        return self.subscribes[url].nodes[index]

    def all_nodes(self) -> list:
        nodes = []
        for url in self.subscribes.keys():
            group = self.subscribes[url]
            nodes.extend(group.nodes)
        nodes.extend(self.resolved_manual_nodes())
        return nodes

    def dump(self, pure=True):
        data = super().dump(pure=pure)
        data['manual_nodes'] = [
            self.resolve_manual_node(node).dump(pure=pure)
            for node in self.manual_nodes
        ]
        return data

    def subscribe_hosts(self) -> list:
        hosts = []
        for url in self.subscribes.keys():
            host = urlparse(url).hostname
            if host:
                hosts.append(host)
        return hosts

    def refresh_update_time(self):
        self.last_subscribe = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
