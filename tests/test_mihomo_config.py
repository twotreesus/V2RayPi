import unittest

import yaml

from core.mihomo_config import MihomoConfig, PROXY_TAG, TPROXY_PORT, DNS_PORT
from core.mihomo_user_config import MihomoUserConfig
from core.node import Node
from core.node_uri import parse_node_uri


def make_node(**overrides):
    proxy = {
        'name': '香港 01',
        'type': 'vmess',
        'server': 'hk.example.com',
        'port': 443,
        'uuid': 'uuid-1',
    }
    proxy.update(overrides)
    return Node.from_clash(proxy)


def make_policy(contents, type_, outbound, enable=True):
    policy = MihomoUserConfig.AdvanceConfig.Policy()
    policy.contents = contents
    policy.type = type_
    policy.outbound = outbound
    policy.enable = enable
    return policy


def generate(user_config, nodes=None, hosts=None):
    node = user_config.node
    nodes = nodes if nodes is not None else ([node] if node.add else [])
    return yaml.safe_load(MihomoConfig.gen_config(user_config, nodes, hosts or []))


class GeneralConfigTest(unittest.TestCase):
    def test_tproxy_listener_and_routing_mark_match_the_iptables_rules(self):
        config = generate(self._config())
        self.assertEqual(config['routing-mark'], 255)
        self.assertEqual(config['listeners'], [{
            'name': 'tproxy-in',
            'type': 'tproxy',
            'port': TPROXY_PORT,
            'listen': '0.0.0.0',
            'udp': True,
        }])

    def test_socks_proxy_can_be_disabled(self):
        user_config = self._config()
        self.assertEqual(generate(user_config)['mixed-port'], 1080)

        user_config.advance_config.inbound.enable_socks_proxy = False
        self.assertNotIn('mixed-port', generate(user_config))

    def test_custom_socks_port_is_used(self):
        user_config = self._config()
        user_config.advance_config.inbound.socks_proxy_port = 7890
        self.assertEqual(generate(user_config)['mixed-port'], 7890)

    def test_log_level_none_maps_to_silent(self):
        user_config = self._config()
        user_config.advance_config.log.level = 'none'
        self.assertEqual(generate(user_config)['log-level'], 'silent')

        user_config.advance_config.log.level = 'debug'
        self.assertEqual(generate(user_config)['log-level'], 'debug')

    def test_sniffer_replaces_the_dokodemo_door_sniffing_block(self):
        sniffer = generate(self._config())['sniffer']
        self.assertTrue(sniffer['enable'])
        self.assertTrue(sniffer['override-destination'])
        self.assertEqual(sorted(sniffer['sniff'].keys()), ['HTTP', 'QUIC', 'TLS'])
        self.assertIn('Mijia Cloud', sniffer['skip-domain'])

    def _config(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        return user_config


class ProxiesTest(unittest.TestCase):
    def test_clash_proxy_is_passed_through_under_a_stable_tag(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node(**{
            'network': 'ws',
            'ws-opts': {'path': '/ray', 'headers': {'Host': 'cdn.example.com'}},
            'tls': True,
        })
        proxy = generate(user_config)['proxies'][0]

        self.assertEqual(proxy['name'], PROXY_TAG)
        self.assertEqual(proxy['ws-opts'], {'path': '/ray', 'headers': {'Host': 'cdn.example.com'}})
        self.assertTrue(proxy['tls'])
        self.assertEqual(proxy['uuid'], 'uuid-1')

    def test_pass_through_does_not_mutate_the_stored_node(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        generate(user_config)
        self.assertEqual(user_config.node.clash['name'], '香港 01')

    def test_mux_is_injected_only_into_stream_protocols(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node(type='vmess')
        self.assertEqual(generate(user_config)['proxies'][0]['smux'], {'enabled': True})

        user_config.advance_config.enable_mux = False
        self.assertEqual(generate(user_config)['proxies'][0]['smux'], {'enabled': False})

    def test_mux_is_stripped_from_datagram_protocols(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node(type='hysteria2', password='p', smux={'enabled': True})
        self.assertNotIn('smux', generate(user_config)['proxies'][0])

    def test_direct_mode_has_no_proxies(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        user_config.proxy_mode = MihomoUserConfig.ProxyMode.Direct.value
        self.assertNotIn('proxies', generate(user_config))


class RulesTest(unittest.TestCase):
    def test_direct_mode_matches_everything_to_direct(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        user_config.proxy_mode = MihomoUserConfig.ProxyMode.Direct.value
        self.assertEqual(generate(user_config)['rules'], ['MATCH,DIRECT'])

    def test_private_networks_are_direct_without_relying_on_geo_data(self):
        rules = generate(self._config())['rules']
        self.assertIn('IP-CIDR,192.168.0.0/16,DIRECT,no-resolve', rules)
        self.assertIn('IP-CIDR,127.0.0.0/8,DIRECT,no-resolve', rules)
        self.assertIn('IP-CIDR6,fc00::/7,DIRECT,no-resolve', rules)

    def test_remote_dns_goes_through_the_proxy_and_local_dns_stays_direct(self):
        rules = generate(self._config())['rules']
        self.assertIn('IP-CIDR,8.8.8.8/32,PROXY,no-resolve', rules)
        self.assertIn('IP-CIDR,119.29.29.29/32,DIRECT,no-resolve', rules)

    def test_ntp_is_direct(self):
        self.assertIn('AND,((NETWORK,udp),(DST-PORT,123)),DIRECT',
                      generate(self._config())['rules'])

    def test_ad_block_can_be_turned_off(self):
        user_config = self._config()
        self.assertIn('GEOSITE,category-ads-all,REJECT', generate(user_config)['rules'])

        user_config.advance_config.block_ad = False
        self.assertNotIn('GEOSITE,category-ads-all,REJECT', generate(user_config)['rules'])

    def test_node_and_subscribe_addresses_are_direct(self):
        user_config = self._config()
        ip_node = make_node(name='ip node', server='203.0.113.9')
        rules = generate(user_config, nodes=[user_config.node, ip_node],
                         hosts=['sub.example.com'])['rules']
        self.assertIn('DOMAIN-SUFFIX,hk.example.com,DIRECT', rules)
        self.assertIn('DOMAIN-SUFFIX,sub.example.com,DIRECT', rules)
        self.assertIn('IP-CIDR,203.0.113.9/32,DIRECT,no-resolve', rules)

    def test_domain_rules_precede_geoip_rules_to_avoid_extra_resolution(self):
        rules = generate(self._config())['rules']
        self.assertLess(rules.index('GEOSITE,cn,DIRECT'),
                        rules.index('GEOIP,CN,DIRECT,no-resolve'))

    def test_global_mode_skips_the_china_allow_list(self):
        user_config = self._config()
        user_config.proxy_mode = MihomoUserConfig.ProxyMode.ProxyGlobal.value
        rules = generate(user_config)['rules']
        self.assertNotIn('GEOSITE,cn,DIRECT', rules)
        self.assertNotIn('GEOIP,CN,DIRECT,no-resolve', rules)
        self.assertEqual(rules[-1], 'MATCH,PROXY')

        user_config.advance_config.proxy_preferred = False
        self.assertEqual(generate(user_config)['rules'][-1], 'MATCH,PROXY')

    def test_smart_routing_fallback_follows_proxy_preferred(self):
        user_config = self._config()
        self.assertEqual(generate(user_config)['rules'][-1], 'MATCH,PROXY')

        user_config.advance_config.proxy_preferred = False
        self.assertEqual(generate(user_config)['rules'][-1], 'MATCH,DIRECT')

    def test_gfw_mode_rules_only_appear_when_direct_preferred_and_geo_data_present(self):
        user_config = self._config()
        gfw_rules = ['GEOSITE,geolocation-!cn,PROXY', 'NOT,((GEOIP,CN)),PROXY']

        rules = generate(user_config)['rules']
        for rule in gfw_rules:
            self.assertNotIn(rule, rules)

        user_config.advance_config.proxy_preferred = False
        rules = generate(user_config)['rules']
        for rule in gfw_rules:
            self.assertNotIn(rule, rules)

        user_config.advance_config.geo_data.current_version = '202608010000'
        rules = generate(user_config)['rules']
        for rule in gfw_rules:
            self.assertIn(rule, rules)
        # Without these two, foreign traffic would fall through to MATCH,DIRECT.
        self.assertEqual(rules[-1], 'MATCH,DIRECT')

    def test_user_policies_keep_their_configured_order(self):
        user_config = self._config()
        user_config.advance_config.policys = [
            make_policy(['domain:a.com'], 'domain', 'proxy'),
            make_policy(['domain:b.com'], 'domain', 'block'),
        ]
        rules = generate(user_config)['rules']
        self.assertLess(rules.index('DOMAIN-SUFFIX,a.com,PROXY'),
                        rules.index('DOMAIN-SUFFIX,b.com,REJECT'))

    def test_disabled_policies_are_ignored(self):
        user_config = self._config()
        user_config.advance_config.policys = [
            make_policy(['domain:a.com'], 'domain', 'proxy', enable=False),
        ]
        self.assertNotIn('DOMAIN-SUFFIX,a.com,PROXY', generate(user_config)['rules'])

    def test_an_unusable_policy_entry_does_not_discard_the_rest(self):
        user_config = self._config()
        user_config.advance_config.policys = [
            make_policy(['ext:file:tag', 'domain:a.com', '  '], 'domain', 'proxy'),
        ]
        rules = generate(user_config)['rules']
        self.assertIn('DOMAIN-SUFFIX,a.com,PROXY', rules)
        self.assertEqual(rules[-1], 'MATCH,PROXY')

    def _config(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        return user_config


class DnsTest(unittest.TestCase):
    def test_remote_resolver_is_reachable_through_the_rules(self):
        dns = generate(self._config())['dns']
        # Without respect-rules mihomo would query 8.8.8.8 in the clear.
        self.assertTrue(dns['respect-rules'])
        self.assertEqual(dns['proxy-server-nameserver'], ['119.29.29.29'])
        self.assertEqual(dns['nameserver'], ['8.8.8.8'])
        self.assertFalse(dns['prefer-h3'])

    def test_listens_on_the_port_the_iptables_redirect_targets(self):
        self.assertEqual(generate(self._config())['dns']['listen'],
                         '0.0.0.0:{0}'.format(DNS_PORT))

    def test_ipv4_only_queries(self):
        self.assertFalse(generate(self._config())['dns']['ipv6'])

    def test_redir_host_keeps_working_for_clients_bypassing_our_resolver(self):
        self.assertEqual(generate(self._config())['dns']['enhanced-mode'], 'redir-host')

    def test_node_subscribe_and_direct_policy_domains_resolve_locally(self):
        user_config = self._config()
        user_config.advance_config.policys = [
            make_policy(['direct.example.com'], 'domain', 'direct'),
            make_policy(['proxied.example.com'], 'domain', 'proxy'),
        ]
        policy = generate(user_config, hosts=['sub.example.com'])['dns']['nameserver-policy']

        self.assertEqual(policy['hk.example.com'], ['119.29.29.29'])
        self.assertEqual(policy['sub.example.com'], ['119.29.29.29'])
        self.assertEqual(policy['direct.example.com'], ['119.29.29.29'])
        self.assertNotIn('proxied.example.com', policy)
        self.assertIn('+.ntp.org', policy)
        self.assertIn('geosite:speedtest', policy)

    def test_china_domains_resolve_locally_only_in_auto_mode(self):
        user_config = self._config()
        self.assertIn('geosite:cn', generate(user_config)['dns']['nameserver-policy'])

        user_config.proxy_mode = MihomoUserConfig.ProxyMode.ProxyGlobal.value
        self.assertNotIn('geosite:cn', generate(user_config)['dns']['nameserver-policy'])

    def test_direct_mode_uses_only_the_local_resolver(self):
        user_config = self._config()
        user_config.proxy_mode = MihomoUserConfig.ProxyMode.Direct.value
        dns = generate(user_config)['dns']
        self.assertEqual(dns['nameserver'], ['119.29.29.29'])
        self.assertFalse(dns['respect-rules'])
        self.assertNotIn('nameserver-policy', dns)

    def test_custom_resolvers_are_used(self):
        user_config = self._config()
        user_config.advance_config.dns.local = '223.5.5.5'
        user_config.advance_config.dns.remote = '1.1.1.1'
        config = generate(user_config)
        self.assertEqual(config['dns']['nameserver'], ['1.1.1.1'])
        self.assertEqual(config['dns']['default-nameserver'], ['223.5.5.5'])
        self.assertIn('IP-CIDR,1.1.1.1/32,PROXY,no-resolve', config['rules'])
        self.assertIn('IP-CIDR,223.5.5.5/32,DIRECT,no-resolve', config['rules'])

    def _config(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        return user_config


class DomainPatternTest(unittest.TestCase):
    def test_prefixes_map_onto_mihomo_rule_types(self):
        cases = {
            'geosite:netflix': 'GEOSITE,netflix',
            'full:a.com': 'DOMAIN,a.com',
            'domain:a.com': 'DOMAIN-SUFFIX,a.com',
            'regexp:^ad.*': 'DOMAIN-REGEX,^ad.*',
            'keyword:ads': 'DOMAIN-KEYWORD,ads',
        }
        for pattern, expected in cases.items():
            head, no_resolve = MihomoConfig.translate_domain_pattern(pattern)
            self.assertEqual(head, expected)
            self.assertFalse(no_resolve)

    def test_bare_pattern_stays_a_substring_match(self):
        # Xray matched unprefixed domains as substrings; DOMAIN-SUFFIX would
        # silently narrow what a user's existing rules match.
        head, _ = MihomoConfig.translate_domain_pattern('sina.com')
        self.assertEqual(head, 'DOMAIN-KEYWORD,sina.com')

    def test_surrounding_whitespace_is_ignored(self):
        head, _ = MihomoConfig.translate_domain_pattern('  domain:a.com  ')
        self.assertEqual(head, 'DOMAIN-SUFFIX,a.com')

    def test_ext_prefix_is_rejected(self):
        with self.assertRaises(ValueError):
            MihomoConfig.translate_domain_pattern('ext:geosite.dat:cn')


class IpPatternTest(unittest.TestCase):
    def test_single_addresses_get_a_host_mask(self):
        self.assertEqual(MihomoConfig.translate_ip_pattern('1.2.3.4'),
                         ('IP-CIDR,1.2.3.4/32', True))
        self.assertEqual(MihomoConfig.translate_ip_pattern('2001:db8::1'),
                         ('IP-CIDR6,2001:db8::1/128', True))

    def test_cidr_is_used_as_written(self):
        self.assertEqual(MihomoConfig.translate_ip_pattern('10.0.0.0/8'),
                         ('IP-CIDR,10.0.0.0/8', True))
        self.assertEqual(MihomoConfig.translate_ip_pattern('2001:db8::/32'),
                         ('IP-CIDR6,2001:db8::/32', True))

    def test_geoip_is_upper_cased(self):
        self.assertEqual(MihomoConfig.translate_ip_pattern('geoip:jp'),
                         ('GEOIP,JP', True))

    def test_negated_geoip_uses_a_logic_rule(self):
        # mihomo's GEOIP has no negation operator.
        self.assertEqual(MihomoConfig.translate_ip_pattern('geoip:!cn'),
                         ('NOT,((GEOIP,CN))', False))

    def test_invalid_address_is_rejected(self):
        with self.assertRaises(ValueError):
            MihomoConfig.translate_ip_pattern('not-an-ip')

    def test_ext_prefix_is_rejected(self):
        with self.assertRaises(ValueError):
            MihomoConfig.translate_ip_pattern('ext:geoip.dat:cn')


class YamlRoundTripTest(unittest.TestCase):
    def test_keys_containing_colons_survive_serialisation(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        text = MihomoConfig.gen_config(user_config, [user_config.node], [])
        policy = yaml.safe_load(text)['dns']['nameserver-policy']
        self.assertIn('geosite:cn', policy)
        self.assertIn('geosite:speedtest', policy)

    def test_unicode_node_names_survive_share_url_round_trip(self):
        user_config = MihomoUserConfig()
        user_config.node = make_node()
        self.assertEqual(parse_node_uri(user_config.node.link)['name'], '香港 01')


if __name__ == '__main__':
    unittest.main()
