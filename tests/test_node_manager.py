import base64
import unittest
from unittest.mock import Mock, patch

import yaml
from requests.structures import CaseInsensitiveDict

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


def response(text, headers=None):
    return Mock(text=text, headers=CaseInsensitiveDict(headers or {}))


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


class SubscribeNameTest(unittest.TestCase):
    def test_profile_title_header_is_saved(self):
        node_group = group()
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'Nexitally'},
            ),
        ):
            NodeManager().update_group(node_group, fill_name=True)

        self.assertEqual(node_group.name, 'Nexitally')

    def test_base64_profile_title_is_decoded(self):
        node_group = group()
        title = base64.b64encode('机场名称'.encode('utf-8')).decode('ascii')
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'base64:' + title},
            ),
        ):
            NodeManager().update_group(node_group, fill_name=True)

        self.assertEqual(node_group.name, '机场名称')

    def test_content_disposition_filename_is_used(self):
        node_group = group()
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'content-disposition': 'attachment; filename="Wings.yaml"'},
            ),
        ):
            NodeManager().update_group(node_group, fill_name=True)

        self.assertEqual(node_group.name, 'Wings')

    def test_hostname_is_used_when_headers_are_missing(self):
        node_group = group('https://sub.airport.example/link/abc')
        with patch(
            'core.node_manager.requests.get',
            return_value=response(CLASH_SUBSCRIPTION),
        ):
            NodeManager().update_group(node_group, fill_name=True)

        self.assertEqual(node_group.name, 'sub.airport.example')

    def test_failed_update_keeps_the_existing_name(self):
        node_group = group()
        node_group.name = 'KeepMe'
        with patch(
            'core.node_manager.requests.get',
            return_value=response(BASE64_SUBSCRIPTION),
        ):
            NodeManager().update_group(node_group)

        self.assertEqual(node_group.name, 'KeepMe')

    def test_existing_name_is_kept_on_successful_update(self):
        node_group = group()
        node_group.name = 'Custom Airport'
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'Nexitally'},
            ),
        ):
            NodeManager().update_group(node_group)

        self.assertEqual(node_group.name, 'Custom Airport')

    def test_update_does_not_fill_an_empty_name(self):
        node_group = group()
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'Nexitally'},
            ),
        ):
            NodeManager().update_group(node_group)

        self.assertEqual(node_group.name, '')

    def test_add_subscribe_uses_the_provided_name(self):
        manager = NodeManager()
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'Nexitally'},
            ),
        ), patch.object(manager, 'save'):
            manager.add_subscribe('https://example.com/sub', 'My Airport')

        self.assertEqual(manager.subscribes['https://example.com/sub'].name, 'My Airport')

    def test_rename_subscribe_updates_the_name(self):
        manager = NodeManager()
        node_group = group()
        node_group.name = 'Old'
        manager.subscribes[node_group.subscribe] = node_group
        with patch.object(manager, 'save'):
            manager.rename_subscribe(node_group.subscribe, '  New Name  ')

        self.assertEqual(node_group.name, 'New Name')

    def test_rename_subscribe_rejects_empty_name(self):
        manager = NodeManager()
        node_group = group()
        node_group.name = 'Keep'
        manager.subscribes[node_group.subscribe] = node_group
        with patch.object(manager, 'save') as save:
            with self.assertRaises(ValueError):
                manager.rename_subscribe(node_group.subscribe, '   ')

        self.assertEqual(node_group.name, 'Keep')
        save.assert_not_called()

    def test_add_subscribe_extracts_name_when_omitted(self):
        manager = NodeManager()
        with patch(
            'core.node_manager.requests.get',
            return_value=response(
                CLASH_SUBSCRIPTION,
                {'profile-title': 'Nexitally'},
            ),
        ), patch.object(manager, 'save'):
            manager.add_subscribe('https://example.com/sub')

        self.assertEqual(manager.subscribes['https://example.com/sub'].name, 'Nexitally')


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
        self.assertEqual(manager.manual_nodes[0].subscribe, url)
        self.assertEqual(manager.manual_nodes[0].airport, 'example.com')

    def test_favorite_uses_the_airport_name(self):
        manager, url = self._manager()
        manager.subscribes[url].name = 'Nexitally'
        with patch.object(manager, 'save'):
            self.assertTrue(manager.favorite_node(url, 0))

        self.assertEqual(manager.manual_nodes[0].airport, 'Nexitally')

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
        self.assertEqual(manager.manual_nodes[0].airport, '')
        save.assert_called_once_with()


class AirportNameTest(unittest.TestCase):
    def _manager_with_named_group(self, name='Nexitally'):
        manager = NodeManager()
        node_group = group()
        node_group.name = name
        node_group.nodes = [
            Node.from_clash({'name': 'HK', 'type': 'vmess', 'server': 'a.com', 'port': 1}),
        ]
        manager.subscribes[node_group.subscribe] = node_group
        return manager, node_group.subscribe

    def test_uses_stamped_airport(self):
        manager = NodeManager()
        node = Node.from_clash({'name': 'HK', 'type': 'vmess', 'server': 'a.com', 'port': 1})
        node.airport = 'Nexitally'
        self.assertEqual(manager.airport_name_for_node(node), 'Nexitally')

    def test_uses_subscribe_url_when_airport_is_empty(self):
        manager, url = self._manager_with_named_group()
        node = Node.from_clash({'name': 'HK', 'type': 'vmess', 'server': 'a.com', 'port': 1})
        node.subscribe = url
        self.assertEqual(manager.airport_name_for_node(node), 'Nexitally')

    def test_finds_subscription_group_for_unstamped_node(self):
        manager, _url = self._manager_with_named_group()
        node = Node.from_clash({'name': 'HK', 'type': 'vmess', 'server': 'a.com', 'port': 1})
        self.assertEqual(manager.airport_name_for_node(node), 'Nexitally')

    def test_manual_node_without_airport_stays_empty(self):
        manager = NodeManager()
        node = Node.from_clash({'name': 'AnyTLS', 'type': 'anytls', 'server': 'example.com', 'port': 443})
        self.assertEqual(manager.airport_name_for_node(node), '')


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
