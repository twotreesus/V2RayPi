import unittest
from unittest.mock import Mock, patch

import yaml

from core.node import Node
from core.node_manager import NodeGroup, NodeManager

CLASH_SUBSCRIPTION = """
port: 7890
proxies:
  - name: HK-vmess
    type: vmess
    server: hk.example.com
    port: 443
    uuid: uuid-1
    alterId: 0
    cipher: auto
    network: ws
    ws-opts:
      path: /ray
      headers:
        Host: cdn.example.com
  - name: JP-hysteria2
    type: hysteria2
    server: jp.example.com
    port: 8443
    password: secret
    obfs: salamander
  - name: SG-mieru
    type: mieru
    server: sg.example.com
    port: 2999
    transport: TCP
    username: user
    password: pass
    multiplexing: MULTIPLEXING_LOW
proxy-groups:
  - name: PROXY
    type: select
    proxies: [HK-vmess]
"""

BASE64_SUBSCRIPTION = 'dm1lc3M6Ly9leUp3Y3lJNklDSmhJbjA9'


def group(url='https://example.com/sub'):
    node_group = NodeGroup()
    node_group.subscribe = url
    return node_group


def response(text):
    return Mock(text=text)


class ClashSubscriptionTest(unittest.TestCase):
    def test_proxies_are_stored_verbatim(self):
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response(CLASH_SUBSCRIPTION)):
            NodeManager().update_group(node_group)

        self.assertEqual([node.ps for node in node_group.nodes],
                         ['HK-vmess', 'JP-hysteria2', 'SG-mieru'])
        vmess = node_group.nodes[0]
        self.assertEqual(vmess.protocol, 'vmess')
        self.assertEqual(vmess.add, 'hk.example.com')
        self.assertEqual(vmess.port, 443)
        self.assertEqual(vmess.clash['ws-opts']['headers']['Host'], 'cdn.example.com')

    def test_mieru_options_survive_without_field_mapping(self):
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response(CLASH_SUBSCRIPTION)):
            NodeManager().update_group(node_group)

        mieru = node_group.nodes[2].clash
        self.assertEqual(mieru['transport'], 'TCP')
        self.assertEqual(mieru['multiplexing'], 'MULTIPLEXING_LOW')
        self.assertEqual(mieru['username'], 'user')

    def test_updating_replaces_the_previous_node_list(self):
        node_group = group()
        node_group.nodes.append(Node.from_clash({'name': 'stale', 'type': 'ss', 'server': 'x'}))
        with patch('core.node_manager.requests.get', return_value=response(CLASH_SUBSCRIPTION)):
            NodeManager().update_group(node_group)

        self.assertNotIn('stale', [node.ps for node in node_group.nodes])

    def test_unsupported_types_are_skipped(self):
        content = yaml.safe_dump({'proxies': [
            {'name': 'ok', 'type': 'vmess', 'server': 'a.com', 'port': 1},
            {'name': 'nope', 'type': 'some-future-protocol', 'server': 'b.com', 'port': 2},
        ]})
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response(content)):
            NodeManager().update_group(node_group)

        self.assertEqual([node.ps for node in node_group.nodes], ['ok'])

    def test_entries_missing_a_name_or_server_are_skipped(self):
        content = yaml.safe_dump({'proxies': [
            {'type': 'vmess', 'server': 'a.com', 'port': 1},
            {'name': 'no-server', 'type': 'vmess', 'port': 1},
            {'name': 'ok', 'type': 'vmess', 'server': 'c.com', 'port': 1},
        ]})
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response(content)):
            NodeManager().update_group(node_group)

        self.assertEqual([node.ps for node in node_group.nodes], ['ok'])


class NonClashSubscriptionTest(unittest.TestCase):
    def test_base64_subscription_is_rejected_and_keeps_existing_nodes(self):
        node_group = group()
        existing = Node.from_clash({'name': 'keep', 'type': 'ss', 'server': 'x.com', 'port': 1})
        node_group.nodes.append(existing)
        with patch('core.node_manager.requests.get', return_value=response(BASE64_SUBSCRIPTION)):
            NodeManager().update_group(node_group)

        self.assertEqual([node.ps for node in node_group.nodes], ['keep'])

    def test_yaml_without_proxies_is_rejected(self):
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response('rules:\n  - MATCH,DIRECT\n')):
            NodeManager().update_group(node_group)

        self.assertEqual(node_group.nodes, [])

    def test_malformed_yaml_is_rejected(self):
        node_group = group()
        with patch('core.node_manager.requests.get', return_value=response('proxies: [{')):
            NodeManager().update_group(node_group)

        self.assertEqual(node_group.nodes, [])


class LegacyNodeTest(unittest.TestCase):
    """Nodes stored before the move to mihomo carry no Clash payload."""

    def _legacy_node(self, name):
        node = Node()
        node.ps = name
        node.add = 'legacy.example.com'
        node.port = 443
        node.protocol = 'hysteria2'
        node.clash = {}
        return node

    def test_legacy_nodes_are_dropped_on_load(self):
        manager = NodeManager()
        node_group = group()
        node_group.nodes = [
            self._legacy_node('old'),
            Node.from_clash({'name': 'new', 'type': 'vmess', 'server': 'a.com', 'port': 1}),
        ]
        manager.subscribes[node_group.subscribe] = node_group
        manager.manual_nodes = [self._legacy_node('old favorite')]

        manager._drop_nodes_without_clash_payload()

        self.assertEqual([node.ps for node in node_group.nodes], ['new'])
        self.assertEqual(manager.manual_nodes, [])
class FavoriteTest(unittest.TestCase):
    def _manager(self):
        manager = NodeManager()
        node_group = group()
        node_group.nodes = [
            Node.from_clash({'name': 'HK', 'type': 'vmess', 'server': 'a.com', 'port': 1}),
        ]
        manager.subscribes[node_group.subscribe] = node_group
        return manager, node_group.subscribe

    def test_favorite_copies_the_node(self):
        manager, url = self._manager()
        with patch.object(manager, 'save'):
            self.assertTrue(manager.favorite_node(url, 0))

        self.assertEqual([node.ps for node in manager.manual_nodes], ['HK'])
        # A copy, so editing the subscription later cannot reach the favorite.
        self.assertIsNot(manager.manual_nodes[0].clash,
                         manager.subscribes[url].nodes[0].clash)

    def test_favoriting_the_same_name_twice_is_refused(self):
        manager, url = self._manager()
        with patch.object(manager, 'save'):
            self.assertTrue(manager.favorite_node(url, 0))
            self.assertFalse(manager.favorite_node(url, 0))

        self.assertEqual(len(manager.manual_nodes), 1)

    def test_share_url_can_be_added_directly_to_favorites(self):
        manager = NodeManager()
        uri = 'anytls://password@example.com:443/?sni=cdn.example.com#AnyTLS'
        with patch.object(manager, 'save') as save:
            self.assertTrue(manager.add_manual_node(uri))
            self.assertFalse(manager.add_manual_node(uri))

        self.assertEqual(len(manager.manual_nodes), 1)
        self.assertEqual(manager.manual_nodes[0].clash['type'], 'anytls')
        self.assertEqual(manager.manual_nodes[0].clash['sni'], 'cdn.example.com')
        save.assert_called_once_with()


class NodeLinkTest(unittest.TestCase):
    def test_link_is_a_protocol_share_url(self):
        node = Node.from_clash({'name': '日本 01', 'type': 'hysteria2',
                                'server': 'jp.example.com', 'port': 443, 'password': 'p'})

        self.assertTrue(node.link.startswith('hysteria2://'))
        self.assertIn('%E6%97%A5%E6%9C%AC%2001', node.link)

    def test_empty_node_has_no_link(self):
        self.assertEqual(Node().link, '')


if __name__ == '__main__':
    unittest.main()
