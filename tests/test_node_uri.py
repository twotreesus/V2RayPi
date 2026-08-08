import unittest

from core.node import Node
from core.node_uri import parse_node_uri


PROXIES = [
    {
        'name': 'VMess WS',
        'type': 'vmess',
        'server': 'vmess.example.com',
        'port': 443,
        'uuid': 'uuid-vmess',
        'alterId': 0,
        'cipher': 'auto',
        'network': 'ws',
        'tls': True,
        'servername': 'cdn.example.com',
        'ws-opts': {
            'path': '/ray',
            'headers': {'Host': 'cdn.example.com'},
        },
    },
    {
        'name': 'VLESS Reality',
        'type': 'vless',
        'server': 'vless.example.com',
        'port': 443,
        'uuid': 'uuid-vless',
        'flow': 'xtls-rprx-vision',
        'tls': True,
        'servername': 'www.example.com',
        'client-fingerprint': 'chrome',
        'reality-opts': {
            'public-key': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
            'short-id': '01234567',
        },
        'network': 'tcp',
    },
    {
        'name': 'Shadowsocks',
        'type': 'ss',
        'server': 'ss.example.com',
        'port': 8388,
        'cipher': 'aes-256-gcm',
        'password': 'p@ss:word',
    },
    {
        'name': 'Trojan WS',
        'type': 'trojan',
        'server': 'trojan.example.com',
        'port': 443,
        'password': 'trojan-password',
        'sni': 'cdn.example.com',
        'network': 'ws',
        'ws-opts': {
            'path': '/trojan',
            'headers': {'Host': 'cdn.example.com'},
        },
    },
    {
        'name': 'Hysteria2',
        'type': 'hysteria2',
        'server': 'hy2.example.com',
        'port': 8443,
        'password': 'hy2-password',
        'sni': 'cdn.example.com',
        'skip-cert-verify': True,
        'obfs': 'salamander',
        'obfs-password': 'obfs-password',
    },
    {
        'name': 'AnyTLS',
        'type': 'anytls',
        'server': 'anytls.example.com',
        'port': 443,
        'password': 'anytls-password',
        'sni': 'cdn.example.com',
        'skip-cert-verify': True,
    },
    {
        'name': 'Mieru',
        'type': 'mieru',
        'server': 'mieru.example.com',
        'port': 2999,
        'username': 'user',
        'password': 'pass',
        'transport': 'TCP',
        'multiplexing': 'MULTIPLEXING_LOW',
    },
]


class NodeUriTest(unittest.TestCase):
    def test_supported_nodes_round_trip_through_share_urls(self):
        for proxy in PROXIES:
            with self.subTest(proxy_type=proxy['type']):
                uri = Node.from_clash(proxy).link
                parsed = parse_node_uri(uri)

                self.assertTrue(uri.startswith(proxy['type'] + '://'))
                self.assertEqual(parsed['type'], proxy['type'])
                self.assertEqual(parsed['name'], proxy['name'])
                self.assertEqual(parsed['server'], proxy['server'])
                self.assertEqual(parsed['port'], proxy['port'])

    def test_protocol_credentials_and_options_survive_round_trip(self):
        fields = {
            'vmess': ('uuid', 'network', 'servername', 'ws-opts'),
            'vless': ('uuid', 'flow', 'servername', 'reality-opts'),
            'ss': ('cipher', 'password'),
            'trojan': ('password', 'sni', 'network', 'ws-opts'),
            'hysteria2': (
                'password', 'sni', 'skip-cert-verify',
                'obfs', 'obfs-password',
            ),
            'anytls': ('password', 'sni', 'skip-cert-verify'),
            'mieru': (
                'username', 'password', 'transport', 'multiplexing',
            ),
        }
        for proxy in PROXIES:
            with self.subTest(proxy_type=proxy['type']):
                parsed = parse_node_uri(Node.from_clash(proxy).link)
                for field in fields[proxy['type']]:
                    self.assertEqual(parsed[field], proxy[field])

    def test_hy2_alias_is_accepted(self):
        parsed = parse_node_uri(
            'hy2://password@example.com:443?sni=cdn.example.com#node',
        )
        self.assertEqual(parsed['type'], 'hysteria2')
        self.assertEqual(parsed['name'], 'node')

    def test_unsupported_scheme_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            parse_node_uri('socks5://example.com:1080')


if __name__ == '__main__':
    unittest.main()
