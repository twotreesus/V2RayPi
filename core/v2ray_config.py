# encoding: utf-8
from enum import Enum
import typing
import socket
import sys
from typing import List
from typing import Dict
from .package import jsonpickle
from .v2ray_user_config import V2RayUserConfig
from .node import Node
from .v2ray_default_path import V2rayDefaultPath

class DontPickleNone:
    def __getstate__(self):
        state = self.__dict__.copy()
        bad_keys =[]
        for key in state.keys():
            if state[key] is None:
                bad_keys.append(key)

        for key in bad_keys:
            state.pop(key)
        return state

class Log:
    class Level(Enum):
        debug = 'debug'
        info = 'info'
        warning = 'warning'
        error = 'error'
        none = 'none'

    def __init__(self):
        self.access:str = V2rayDefaultPath.access_log()
        self.error:str = V2rayDefaultPath.error_log()
        self.loglevel:str = self.Level.warning.value

class DomainStrategy(Enum):
    AsIs = 'AsIs'
    UseIP = 'UseIP'
    UseIPv4 = 'UseIPv4'
    UseIPv6 = 'UseIPv6'
    IPIfNonMatch = 'IPIfNonMatch'
    IPOnDemand = 'IPOnDemand'

class DNS(DontPickleNone):
    class Server(DontPickleNone):
        def __init__(self):
            self.address:str = ''
            self.port:int = 53
            self.domains:List[str] = []

        def add_domain(self, domain:str):
            self.domains.append(domain)

    def __init__(self):
        self.queryStrategy = DomainStrategy.UseIPv4.value
        self.hosts:typing.Optional[Dict] = None
        self.servers:List = []

    def add_static_host(self, host:str, ip:str):
        self.hosts[host] = ip

    def add_simple_server(self, server:str):
        self.servers.append(server)

    def add_server(self, server:Server):
        self.servers.append(server)

class ProtocolType(Enum):
    blackhole = 'blackhole'
    dokodemo_door = 'dokodemo-door'
    freedom = 'freedom'
    socks = 'socks'
    vmess = 'vmess'
    dns = 'dns'

class NetworkType(Enum):
    tcp = 'tcp'
    udp = 'udp'
    tcp_udp = 'tcp,udp'

class ProtocolBlackHole:
    type = ProtocolType.blackhole.value
    class Settings:
        class ResponseType:
            class Type(Enum):
                none = 'none'
                http = 'http'
            def __init__(self):
                self.type = self.Type.http.value
        def __init__(self):
            self.response = self.ResponseType()

class ProtocolDokodemoDoor:
    type = ProtocolType.dokodemo_door.value
    class Settings(DontPickleNone):
        def __init__(self):
            self.address:typing.Optional[str] = None
            self.port:typing.Optional[int] = None
            self.network:str = NetworkType.tcp_udp.value
            self.timeout:typing.Optional[int] = None
            self.followRedirect:bool = True

class ProtocolFreedom:
    type = ProtocolType.freedom.value
    class Settings(DontPickleNone):
        def __init__(self):
            self.domainStrategy = DomainStrategy.UseIPv4.value
            self.redirect:typing.Optional[str] = None
            self.userLevel:typing.Optional[int] = None

class ProtocolSocks:
    type = ProtocolType.socks.value
    class Settings(DontPickleNone):
        def __init__(self):
            self.auth = 'noauth'
            if sys.platform != 'darwin':
                self.udp:typing.Optional[bool] = True
            self.ip:typing.Optional[str] = None
            self.userLevel:typing.Optional[int] = None

class ProtocolVMess:
    type = ProtocolType.vmess.value
    class Settings:
        class Server:
            class User(DontPickleNone):
                class Security(Enum):
                    aes_128_gcm = 'aes-128-gcm'
                    chacha20_poly1305 = 'chacha20-poly1305'
                    auto = 'auto'
                    none = 'none'

                def __init__(self):
                    self.id:str = ''
                    self.alterId:int = 0
                    self.security:str = self.Security.auto.value
                    self.level:int = 0

            def __init__(self):
                self.address:str = ''
                self.port:int = 0
                self.users:List[ProtocolVMess.Settings.Server.User] = []

            def add_user(self, user:User):
                self.users.append(user)

        def __init__(self):
            self.vnext:List[ProtocolVMess.Settings.Server] = []

        def add_server(self, server:Server):
            self.vnext.append(server)

class ProtocolDNS:
    type = ProtocolType.dns.value
    class Settings:
        pass

class StreamSettings(DontPickleNone):
    class Network(Enum):
        tcp = 'tcp'
        kcp = 'kcp'
        ws = 'ws'
        http = 'http'
        domainsocket = 'domainsocket'
        quic = 'quic'

    class Security(Enum):
        none = 'none'
        tls = 'tls'
    class TCP:
        def __init__(self):
            self.header = { }

        def _makeRequest(self):
            if not 'request' in self.header:
                self.header['request'] = {}
        def setHeaderType(self, type):
            self.header['type'] = type
        def setHost(self, host):
            self._makeRequest()
            self.header['request']['headers'] = { 'Host' : [ host, ] }
        def setPath(self, path):
            self._makeRequest()
            self.header['request']['path'] = [ path, ]

    class WebSocket:
        def __init__(self):
            self.path:str = '/'
            self.headers:Dict[str, str] = {}
        def setHost(self, host:str):
            self.headers['Host'] = host
    class TLS(DontPickleNone):
        def __init__(self):
            self.serverName:str = ''
            self.allowInsecure:bool = False
            self.alpn = None
    class SockOpt(DontPickleNone):
        class TProxy(Enum):
            redirect = 'redirect'
            tproxy = 'tproxy'
            off = 'off'
        def __init__(self):
            self.mark:typing.Optional[int] = None
            self.tcpFastOpen:typing.Optional[bool] = None
            self.tproxy:typing.Optional[str] = None
    def __init__(self):
        self.network:typing.Optional[str] = None
        self.security:typing.Optional[str] = None
        self.tcpSettings:typing.Optional[StreamSettings.TCP] = None
        self.wsSettings:typing.Optional[StreamSettings.WebSocket] = None
        self.tlsSettings:typing.Optional[StreamSettings.TLS] = None
        self.sockopt:typing.Optional[StreamSettings.SockOpt] = None

class Inbound(DontPickleNone):
    class Sniffing:
        def __init__(self):
            self.enabled:bool = True
            self.destOverride = ["http", "tls"]
            self.excludedDomain:str = "Mijia Cloud"

    def __init__(self):
        self.port:int = 0
        self.listen:typing.Optional[str] = None
        self.protocol:str = ''
        self.settings = None
        self.sniffing: typing.Optional[Inbound.Sniffing] = None
        self.streamSettings:typing.Optional[StreamSettings] = None
        self.tag: typing.Optional[str] = None

class Outbound(DontPickleNone):
    class Mux(DontPickleNone):
        def __init__(self):
            self.enabled:bool = True
            self.concurrency:typing.Optional[int] = None
    def __init__(self):
        self.mux: typing.Optional[Outbound.Mux] = None
        self.sendThrough:typing.Optional[str] = None
        self.protocol:str = ''
        self.settings = None
        self.streamSettings:typing.Optional[StreamSettings] = StreamSettings()
        self.streamSettings.sockopt = StreamSettings.SockOpt()
        self.streamSettings.sockopt.mark = 255
        self.tag: str = ''

class Routing:
    class Rule(DontPickleNone):
        def __init__(self):
            self.type = 'field'
            self.inboundTag: typing.Optional[List[str]] = None
            self.domain:typing.Optional[List[str]] = None
            self.ip:typing.Optional[List[str]] = None
            self.port:typing.Optional[str] = None
            self.network:typing.Optional[str] = None
            self.source:typing.Optional[List[str]] = None
            self.protocol:typing.Optional[List[str]] = None
            self.outboundTag:str = ''
        def add_inbound_tag(self, tag:str):
            if not self.inboundTag:
                self.inboundTag = []
            self.inboundTag.append(tag)
        def add_domain(self, domain:str):
            if not self.domain:
                self.domain = []
            self.domain.append(domain)
        def add_ip(self, ip:str):
            if not self.ip:
                self.ip = []
            self.ip.append(ip)
        def add_protocol(self, protocol:str):
            if not self.protocol:
                self.protocol = []
            self.protocol.append(protocol)

    def __init__(self):
        self.domainStrategy:str = DomainStrategy.IPOnDemand.value
        self.rules:List[Routing.Rule] = []

class Tags(Enum):
    transparent = 'transparent'
    direct = 'direct'
    proxy = 'proxy'
    block = 'block'
    dnsout = 'dns-out'

class V2RayConfig(DontPickleNone):
    def __init__(self):
        self.log:Log = Log()
        self.inbounds:List[Inbound] = []
        self.outbounds:List[Outbound] = []
        self.dns: typing.Optional[DNS] = None
        self.routing:Routing = Routing()

    def add_inbound(self, inbound:Inbound):
        self.inbounds.append(inbound)

    def add_outbound(self, outbound:Outbound):
        self.outbounds.append(outbound)

    @classmethod
    def gen_config(cls, user_config:V2RayUserConfig, all_nodes: List[Node]) -> str:
        config = V2RayConfig()

        # prepare all nodes addr
        all_node_domains = set()
        all_node_ips = set()
        for node in all_nodes:
            node:Node
            try:
                socket.inet_aton(node.add)
                all_node_ips.add(node.add)
            except socket.error:
                all_node_domains.add(node.add)

        # log
        config.log.loglevel = Log.Level[user_config.advance_config.log.level].name

        # inbounds
        if sys.platform != 'darwin':
            dokodemo_door = cls._make_inbound_dokodemo_door()
            config.add_inbound(dokodemo_door)
        if user_config.advance_config.inbound.enable_socks_proxy :
            socks = cls._make_inbound_socks(user_config.advance_config.inbound.socks_port())
            config.add_inbound(socks)

        # outbonds
        direct = cls._make_outbound_direct()
        if user_config.proxy_mode == V2RayUserConfig.ProxyMode.Direct.value:
            config.add_outbound(direct)
        else:
            proxy = cls._make_outbound_proxy(user_config.node, user_config.advance_config.enable_mux)
            block = cls._make_outbound_block()
            dnsout = cls._make_outbound_dnsout()
            if user_config.advance_config.proxy_preferred:
                config.outbounds.extend((proxy, direct, block, dnsout))
            else:
                config.outbounds.extend((direct, proxy, block, dnsout))

        # dns
        if user_config.proxy_mode != V2RayUserConfig.ProxyMode.Direct.value:
            config.dns = DNS()
            config.dns.add_simple_server(user_config.advance_config.dns.remote_dns())

            local_server = DNS.Server()
            local_server.address = user_config.advance_config.dns.local_dns()
            local_server.add_domain('ntp.org')
            local_server.add_domain('geosite:speedtest')

            # all node domains should use local dns
            for addr in all_node_domains:
                local_server.add_domain(addr)

            if user_config.proxy_mode == V2RayUserConfig.ProxyMode.ProxyAuto.value:
                local_server.add_domain('geosite:cn')

            # user direct domain use local dns
            for policy in user_config.advance_config.policys:
                policy:V2RayUserConfig.AdvanceConfig.Policy
                if (policy.enable and
                        policy.type == V2RayUserConfig.AdvanceConfig.Policy.Type.domain.name and
                        policy.outbound == V2RayUserConfig.AdvanceConfig.Policy.Outbound.direct.name):
                    for domain in policy.contents:
                        local_server.add_domain(domain)

            config.dns.add_server(local_server)

        # routing
        if user_config.proxy_mode != V2RayUserConfig.ProxyMode.Direct.value:
            dnsout = cls._make_dnsout_rule()
            ntp = cls._make_ntp_rule()
            bt = cls._make_bt_rule()
            private = cls._make_private_rule()
            remote_dns = cls._make_ip_remote_dns_rule(user_config.advance_config.dns.remote_dns())
            local_dns = cls._make_ip_local_dns_rule(user_config.advance_config.dns.local_dns())
            config.routing.rules.extend((dnsout, ntp, bt, private, local_dns, remote_dns))

            if user_config.advance_config.block_ad :
                adblock = cls._make_adblock_rule()
                config.routing.rules.append(adblock)

            # all node domains direct rule
            if len(all_node_domains):
                all_node_domain_rule = cls._make_user_domain_rule(list(all_node_domains), V2RayUserConfig.AdvanceConfig.Policy.Outbound.direct)
                config.routing.rules.append(all_node_domain_rule)

            # all node ips direct rule
            if len(all_node_ips):
                all_node_ip_rule = cls._make_user_ip_rule(list(all_node_ips), V2RayUserConfig.AdvanceConfig.Policy.Outbound.direct)
                config.routing.rules.append(all_node_ip_rule)

            # user rules
            for policy in user_config.advance_config.policys:
                if policy.enable:
                    rule = None
                    if policy.type == V2RayUserConfig.AdvanceConfig.Policy.Type.ip.name:
                        rule = cls._make_user_ip_rule(policy.contents, V2RayUserConfig.AdvanceConfig.Policy.Outbound[policy.outbound])
                    elif policy.type == V2RayUserConfig.AdvanceConfig.Policy.Type.domain.name:
                        rule = cls._make_user_domain_rule(policy.contents, V2RayUserConfig.AdvanceConfig.Policy.Outbound[policy.outbound])
                    config.routing.rules.append(rule)

            if user_config.proxy_mode == V2RayUserConfig.ProxyMode.ProxyAuto.value:
                ip_cn = cls._make_ip_cn_rule()
                site_cn = cls._make_site_cn_rule()
                config.routing.rules.extend((ip_cn, site_cn))

        raw_config = jsonpickle.encode(config, unpicklable=False, indent=4)
        return raw_config

    @classmethod
    def _make_inbound_dokodemo_door(self) -> Inbound :
        dokodemo_door = Inbound()
        dokodemo_door.tag = Tags.transparent.value
        dokodemo_door.protocol = ProtocolDokodemoDoor.type
        dokodemo_door.port = 12345
        dokodemo_door.sniffing = Inbound.Sniffing()

        settings = ProtocolDokodemoDoor.Settings()
        dokodemo_door.settings = settings

        stream_settings = StreamSettings()
        stream_settings.sockopt = StreamSettings.SockOpt()
        stream_settings.sockopt.tproxy = StreamSettings.SockOpt.TProxy.tproxy.value
        dokodemo_door.streamSettings = stream_settings

        return dokodemo_door

    @classmethod
    def _make_inbound_socks(cls, port) -> Inbound:
        socks = Inbound()
        socks.protocol = ProtocolSocks.type
        socks.port = port
        socks.sniffing = Inbound.Sniffing()

        settings = ProtocolSocks.Settings()
        socks.settings = settings

        return socks

    @classmethod
    def _make_outbound_direct(cls) -> Outbound:
        direct = Outbound()
        direct.tag = Tags.direct.value
        direct.protocol = ProtocolFreedom.type
        direct.settings = ProtocolFreedom.Settings()

        return direct

    @classmethod
    def _make_outbound_proxy(cls, node:Node, enable_mux:bool) -> Outbound:
        proxy = Outbound()
        proxy.tag = Tags.proxy.value
        proxy.protocol = ProtocolVMess.type

        user = ProtocolVMess.Settings.Server.User()
        user.alterId = int(node.aid)
        user.id = node.id
        if node.scy:
            user.security = node.scy

        server = ProtocolVMess.Settings.Server()
        server.add_user(user)
        server.address = node.add
        server.port = int(node.port)

        settings = ProtocolVMess.Settings()
        settings.add_server(server)
        proxy.settings = settings

        # stream settings
        stream_settings = proxy.streamSettings
        if node.tls != StreamSettings.Security.tls.value:
            stream_settings.security = StreamSettings.Security.none.value
        else:
            stream_settings.security = StreamSettings.Security.tls.value

            tls = StreamSettings.TLS()
            if node.alpn:
                tls.alpn = [ node.alpn, ]
            if node.sni:
                tls.serverName = node.sni
            else:
                tls.serverName = node.host
            stream_settings.tlsSettings = tls

        stream_settings.network = node.net
        if node.net == StreamSettings.Network.tcp.value:
            if node.type != 'none':
                stream_settings.tcpSettings = StreamSettings.TCP()
                stream_settings.tcpSettings.setHeaderType(node.type)
                stream_settings.tcpSettings.setHost(node.host)
                stream_settings.tcpSettings.setPath(node.path)
        elif node.net == StreamSettings.Network.ws.value:
            stream_settings.wsSettings = StreamSettings.WebSocket()
            stream_settings.wsSettings.path = node.path
            stream_settings.wsSettings.setHost(node.host)

        proxy.mux = Outbound.Mux()
        proxy.mux.enabled = enable_mux

        return proxy

    @classmethod
    def _make_outbound_block(cls) -> Outbound:
        block = Outbound()
        block.tag = Tags.block.value
        block.protocol = ProtocolBlackHole.type
        block.settings = ProtocolBlackHole.Settings()
        block.streamSettings = None

        return block

    @classmethod
    def _make_outbound_dnsout(cls) -> Outbound:
        dnsout = Outbound()
        dnsout.tag = Tags.dnsout.value
        dnsout.protocol = ProtocolDNS.type

        return dnsout

    @classmethod
    def _make_dnsout_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_inbound_tag(Tags.transparent.value)
        rule.network = NetworkType.udp.value
        rule.port = 53
        rule.outboundTag = Tags.dnsout.value

        return rule

    @classmethod
    def _make_ntp_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_inbound_tag(Tags.transparent.value)
        rule.network = NetworkType.udp.value
        rule.port = 123
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_adblock_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_domain('geosite:category-ads-all')
        rule.outboundTag = Tags.block.value

        return rule

    @classmethod
    def _make_bt_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_protocol('bittorrent')
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_private_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_ip('geoip:private')
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_ip_cn_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_ip('geoip:cn')
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_site_cn_rule(cls) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_domain('geosite:cn')
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_ip_local_dns_rule(cls, local_dns:str) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_ip(local_dns)
        rule.outboundTag = Tags.direct.value

        return rule

    @classmethod
    def _make_ip_remote_dns_rule(cls, remote_dns:str) -> Routing.Rule:
        rule = Routing.Rule()
        rule.add_ip(remote_dns)
        rule.outboundTag = Tags.proxy.value

        return rule

    @classmethod
    def _make_user_domain_rule(cls, domains:List[str], outbound:V2RayUserConfig.AdvanceConfig.Policy.Outbound):
        rule = Routing.Rule()
        for domain in domains:
            rule.add_domain(domain)
        rule.outboundTag = cls._tag_from_outband(outbound)
        return rule

    @classmethod
    def _make_user_ip_rule(cls, ips:List[str], outbound:V2RayUserConfig.AdvanceConfig.Policy.Outbound):
        rule = Routing.Rule()
        for ip in ips:
            rule.add_ip(ip)
        rule.outboundTag = cls._tag_from_outband(outbound)
        return rule

    @classmethod
    def _tag_from_outband(cls, outbound:V2RayUserConfig.AdvanceConfig.Policy.Outbound) ->str:
        tag = ''
        if outbound == V2RayUserConfig.AdvanceConfig.Policy.Outbound.direct:
            tag = Tags.direct.value
        elif outbound == V2RayUserConfig.AdvanceConfig.Policy.Outbound.proxy:
            tag = Tags.proxy.value
        elif outbound == V2RayUserConfig.AdvanceConfig.Policy.Outbound.block:
            tag = Tags.block.value
        return tag