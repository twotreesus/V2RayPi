# encoding: utf-8
"""Generates the mihomo configuration applied to the transparent proxy.

Only the currently selected node is written into ``proxies``, so switching
nodes rewrites this file and reloads the core.  The node is passed through
from the Clash subscription untouched, which is why this module does not
need per-protocol field mapping.
"""
from __future__ import annotations

import copy
import ipaddress
from typing import Dict, List, Optional, Tuple

import yaml

from .mihomo_user_config import MihomoUserConfig
from .node import Node

PROXY_TAG = 'PROXY'
DIRECT_TAG = 'DIRECT'
REJECT_TAG = 'REJECT'

TPROXY_PORT = 12345
DNS_PORT = 1053
ROUTING_MARK = 255

# Proxy types mihomo can serve as an outbound.  Subscriptions are filtered
# against this list before a node is stored, because a single unsupported
# entry would otherwise be able to make the whole generated config invalid.
SUPPORTED_PROXY_TYPES = frozenset({
    'ss', 'ssr', 'vmess', 'vless', 'trojan', 'snell',
    'anytls', 'mieru', 'hysteria', 'hysteria2', 'tuic',
    'wireguard', 'ssh', 'socks5', 'http',
})

# Multiplexing only applies to stream-based protocols.  Injecting `smux` into
# a datagram protocol such as hysteria2 makes mihomo reject the config.
MUX_CAPABLE_PROXY_TYPES = frozenset({'vmess', 'vless', 'trojan', 'ss'})

# Xray log levels as exposed by the advance settings page, mapped onto the
# names mihomo accepts.
LOG_LEVELS = {
    'debug': 'debug',
    'info': 'info',
    'warning': 'warning',
    'error': 'error',
    'none': 'silent',
}

# Replaces Xray's `geoip:private`.  Written out explicitly rather than relying
# on a geo category, because losing this rule costs LAN reachability and the
# SSH access needed to recover the device.
PRIVATE_NETWORKS = (
    '127.0.0.0/8',
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
    '169.254.0.0/16',
    '100.64.0.0/10',
    '224.0.0.0/4',
    '255.255.255.255/32',
)
PRIVATE_NETWORKS_V6 = (
    '::1/128',
    'fc00::/7',
    'fe80::/10',
)


class MihomoConfig:
    @classmethod
    def gen_config(cls, user_config: MihomoUserConfig, all_nodes: List[Node],
                   subscribe_hosts: Optional[List[str]] = None) -> str:
        domains, ips = cls._split_addrs(all_nodes, subscribe_hosts)
        direct_domains = cls._direct_policy_domains(user_config)

        config = cls._gen_general(user_config)
        config['sniffer'] = cls._gen_sniffer()
        config['dns'] = cls._gen_dns(user_config, domains, direct_domains)

        proxies = cls._gen_proxies(user_config)
        if proxies:
            config['proxies'] = proxies
        config['rules'] = cls._gen_rules(user_config, domains, ips)

        return yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False)

    @classmethod
    def _split_addrs(cls, all_nodes: List[Node],
                     subscribe_hosts: Optional[List[str]]) -> Tuple[List[str], List[str]]:
        domains = set()
        ips = set()
        addrs = [node.add for node in all_nodes if node.add]
        addrs.extend(subscribe_hosts or [])
        for addr in addrs:
            try:
                ipaddress.ip_address(addr)
                ips.add(addr)
            except ValueError:
                domains.add(addr)
        return sorted(domains), sorted(ips)

    @classmethod
    def _direct_policy_domains(cls, user_config: MihomoUserConfig) -> List[str]:
        policy_type = MihomoUserConfig.AdvanceConfig.Policy
        domains = []
        for policy in user_config.advance_config.policys:
            if (policy.enable
                    and policy.type == policy_type.Type.domain.name
                    and policy.outbound == policy_type.Outbound.direct.name):
                domains.extend(policy.contents)
        return domains

    @classmethod
    def _gen_general(cls, user_config: MihomoUserConfig) -> Dict:
        config = {
            'mode': 'rule',
            'log-level': LOG_LEVELS.get(user_config.advance_config.log.level, 'warning'),
            'allow-lan': True,
            'bind-address': '*',
            # 255 == 0xff, matching the `-m mark --mark 0xff -j RETURN` rules in
            # script/config_iptable.sh that keep mihomo's own upstream
            # connections from looping back into TPROXY.
            'routing-mark': ROUTING_MARK,
            # Reuse the V2Ray-format geoip.dat / geosite.dat that the GEO
            # database update feature already downloads.  memconservative keeps
            # the footprint down on small single-board computers.
            'geodata-mode': True,
            'geodata-loader': 'memconservative',
            'listeners': [
                {
                    'name': 'tproxy-in',
                    'type': 'tproxy',
                    'port': TPROXY_PORT,
                    'listen': '0.0.0.0',
                    'udp': True,
                }
            ],
        }
        if user_config.advance_config.inbound.enable_socks_proxy:
            config['mixed-port'] = user_config.advance_config.inbound.socks_port()
        return config

    @classmethod
    def _gen_sniffer(cls) -> Dict:
        # Replaces the dokodemo-door `sniffing` block: recovers the domain from
        # SNI/Host so domain rules keep working for clients that resolved names
        # through a resolver other than ours.
        return {
            'enable': True,
            'override-destination': True,
            'sniff': {
                'HTTP': {'ports': [80, '8080-8880']},
                'TLS': {'ports': [443, 8443]},
                'QUIC': {'ports': [443, 8443]},
            },
            'skip-domain': ['Mijia Cloud'],
        }

    @classmethod
    def _gen_dns(cls, user_config: MihomoUserConfig, node_domains: List[str],
                 direct_domains: List[str]) -> Dict:
        dns_config = user_config.advance_config.dns
        local = dns_config.local_dns()
        remote = dns_config.remote_dns()

        dns = {
            'enable': True,
            'listen': '0.0.0.0:{0}'.format(DNS_PORT),
            # Matches the IPv4-only query strategy the Xray config used.
            'ipv6': False,
            'enhanced-mode': 'redir-host',
            'use-hosts': True,
            'prefer-h3': False,
            'default-nameserver': [local],
        }

        if user_config.proxy_mode == MihomoUserConfig.ProxyMode.Direct.value:
            dns['respect-rules'] = False
            dns['nameserver'] = [local]
            return dns

        # A plaintext query to the remote resolver is useless unless it is sent
        # through the proxy.  mihomo skips `rules` for its own DNS traffic
        # unless respect-rules is on, and requires proxy-server-nameserver to
        # be set when it is, so that resolving the node's own address does not
        # deadlock on the proxy it is trying to build.
        dns['respect-rules'] = True
        dns['proxy-server-nameserver'] = [local]
        dns['nameserver'] = [remote]

        policy = {}
        for domain in node_domains:
            policy[domain] = [local]
        for domain in direct_domains:
            policy[domain] = [local]
        policy['+.ntp.org'] = [local]
        policy['geosite:speedtest'] = [local]
        if user_config.proxy_mode == MihomoUserConfig.ProxyMode.ProxyAuto.value:
            policy['geosite:cn'] = [local]
        dns['nameserver-policy'] = policy

        return dns

    @classmethod
    def _gen_proxies(cls, user_config: MihomoUserConfig) -> List[Dict]:
        if user_config.proxy_mode == MihomoUserConfig.ProxyMode.Direct.value:
            return []

        node = user_config.node
        clash = getattr(node, 'clash', None)
        if not clash:
            return []

        proxy = copy.deepcopy(clash)
        # Node names come from the subscription and are arbitrary text.  The
        # rules below reference the outbound by name, so pin it to a stable tag.
        proxy['name'] = PROXY_TAG

        if proxy.get('type') in MUX_CAPABLE_PROXY_TYPES:
            proxy['smux'] = {'enabled': bool(user_config.advance_config.enable_mux)}
        else:
            proxy.pop('smux', None)

        return [proxy]

    @classmethod
    def _gen_rules(cls, user_config: MihomoUserConfig, node_domains: List[str],
                   node_ips: List[str]) -> List[str]:
        if user_config.proxy_mode == MihomoUserConfig.ProxyMode.Direct.value:
            return ['MATCH,{0}'.format(DIRECT_TAG)]

        advance = user_config.advance_config
        rules: List[str] = []

        rules.append('AND,((NETWORK,udp),(DST-PORT,123)),{0}'.format(DIRECT_TAG))

        for network in PRIVATE_NETWORKS:
            rules.append(cls._rule('IP-CIDR,{0}'.format(network), DIRECT_TAG, no_resolve=True))
        for network in PRIVATE_NETWORKS_V6:
            rules.append(cls._rule('IP-CIDR6,{0}'.format(network), DIRECT_TAG, no_resolve=True))

        rules.append(cls._rule(cls._ip_head(advance.dns.local_dns()), DIRECT_TAG, no_resolve=True))
        rules.append(cls._rule(cls._ip_head(advance.dns.remote_dns()), PROXY_TAG, no_resolve=True))

        if advance.block_ad:
            rules.append('GEOSITE,category-ads-all,{0}'.format(REJECT_TAG))

        for domain in node_domains:
            rules.append('DOMAIN-SUFFIX,{0},{1}'.format(domain, DIRECT_TAG))
        for ip in node_ips:
            rules.append(cls._rule(cls._ip_head(ip), DIRECT_TAG, no_resolve=True))

        rules.extend(cls._gen_policy_rules(user_config))

        if user_config.proxy_mode == MihomoUserConfig.ProxyMode.ProxyAuto.value:
            # GEOSITE first: a GEOIP rule matched against a domain would
            # trigger a resolution that the domain rule makes unnecessary.
            rules.append('GEOSITE,cn,{0}'.format(DIRECT_TAG))
            rules.append(cls._rule('GEOIP,CN', DIRECT_TAG, no_resolve=True))

            # Direct preferred is a list mode: only the recognised foreign sites
            # are worth the proxy and the DIRECT fallback below keeps everything
            # else local.  Judging the rest by their resolved IP instead would
            # send every unlisted foreign host through the proxy as well, which
            # is what proxy preferred already does.
            if not advance.proxy_preferred:
                rules.append('GEOSITE,geolocation-!cn,{0}'.format(PROXY_TAG))

        fallback = PROXY_TAG
        if (user_config.proxy_mode == MihomoUserConfig.ProxyMode.ProxyAuto.value
                and not advance.proxy_preferred):
            fallback = DIRECT_TAG
        rules.append('MATCH,{0}'.format(fallback))

        return rules

    @classmethod
    def _gen_policy_rules(cls, user_config: MihomoUserConfig) -> List[str]:
        policy_type = MihomoUserConfig.AdvanceConfig.Policy
        rules = []
        for policy in user_config.advance_config.policys:
            if not policy.enable:
                continue
            tag = cls._tag_from_outbound(policy.outbound)
            if not tag:
                print('Skipped routing policy with unknown outbound: {0}'.format(policy.outbound))
                continue
            for content in policy.contents:
                content = (content or '').strip()
                if not content:
                    continue
                try:
                    if policy.type == policy_type.Type.ip.name:
                        head, no_resolve = cls.translate_ip_pattern(content)
                    elif policy.type == policy_type.Type.domain.name:
                        head, no_resolve = cls.translate_domain_pattern(content)
                    else:
                        raise ValueError('unknown policy type: {0}'.format(policy.type))
                except ValueError as error:
                    # A single unusable rule must not stop the whole config
                    # from being generated, or the router would stay offline.
                    print('Skipped routing rule "{0}": {1}'.format(content, error))
                    continue
                rules.append(cls._rule(head, tag, no_resolve=no_resolve))
        return rules

    @classmethod
    def translate_domain_pattern(cls, pattern: str) -> Tuple[str, bool]:
        pattern = pattern.strip()
        if pattern.startswith('geosite:'):
            return 'GEOSITE,{0}'.format(pattern[len('geosite:'):]), False
        if pattern.startswith('full:'):
            return 'DOMAIN,{0}'.format(pattern[len('full:'):]), False
        if pattern.startswith('domain:'):
            return 'DOMAIN-SUFFIX,{0}'.format(pattern[len('domain:'):]), False
        if pattern.startswith('regexp:'):
            return 'DOMAIN-REGEX,{0}'.format(pattern[len('regexp:'):]), False
        if pattern.startswith('keyword:'):
            return 'DOMAIN-KEYWORD,{0}'.format(pattern[len('keyword:'):]), False
        if pattern.startswith('ext:'):
            raise ValueError('ext: is not supported by mihomo, use geosite: instead')
        # An unprefixed pattern was a substring match in the Xray config.
        # DOMAIN-KEYWORD keeps that meaning; DOMAIN-SUFFIX would silently
        # narrow what the user's existing rules match.
        return 'DOMAIN-KEYWORD,{0}'.format(pattern), False

    @classmethod
    def translate_ip_pattern(cls, pattern: str) -> Tuple[str, bool]:
        pattern = pattern.strip()
        if pattern.startswith('geoip:'):
            code = pattern[len('geoip:'):]
            # A geo rule asks where the destination is, which cannot be answered
            # for a domain without resolving it, so neither form carries
            # no-resolve.  The negated one has to be a logic rule because mihomo's
            # GEOIP has no negation operator, and no-resolve cannot be bolted onto
            # it either way: appended, mihomo reads it as the target proxy, and
            # inside the inner rule it inverts into matching every domain.
            if code.startswith('!'):
                return 'NOT,((GEOIP,{0}))'.format(code[1:].upper()), False
            return 'GEOIP,{0}'.format(code.upper()), False
        if pattern.startswith('ext:'):
            raise ValueError('ext: is not supported by mihomo, use geoip: instead')
        return cls._ip_head(pattern), True

    @classmethod
    def _ip_head(cls, addr: str) -> str:
        addr = addr.strip()
        if '/' in addr:
            network = ipaddress.ip_network(addr, strict=False)
            prefix = 'IP-CIDR' if network.version == 4 else 'IP-CIDR6'
            return '{0},{1}'.format(prefix, addr)
        ip = ipaddress.ip_address(addr)
        if ip.version == 4:
            return 'IP-CIDR,{0}/32'.format(addr)
        return 'IP-CIDR6,{0}/128'.format(addr)

    @classmethod
    def _rule(cls, head: str, policy: str, no_resolve: bool = False) -> str:
        if no_resolve:
            return '{0},{1},no-resolve'.format(head, policy)
        return '{0},{1}'.format(head, policy)

    @classmethod
    def _tag_from_outbound(cls, outbound: str) -> str:
        outbounds = MihomoUserConfig.AdvanceConfig.Policy.Outbound
        if outbound == outbounds.direct.name:
            return DIRECT_TAG
        if outbound == outbounds.proxy.name:
            return PROXY_TAG
        if outbound == outbounds.block.name:
            return REJECT_TAG
        return ''
