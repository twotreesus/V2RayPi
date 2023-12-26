# encoding: utf-8
from enum import Enum, auto
from typing import List
from .base_data_item import BaseDataItem
from .node import Node

class V2RayUserConfig(BaseDataItem):
    class ProxyMode(Enum):
        Direct = 0
        ProxyAuto = 1
        ProxyGlobal = 2

    class AdvanceConfig(BaseDataItem):
        class Log:
            def __init__(self):
                self.level = 'warning'
        class InBound:
            def __init__(self):
                self.enable_socks_proxy:bool = True
                self.socks_proxy_port:int = 0
                self.default_socks_proxy_port = 1080
            def socks_port(self) -> int:
                if self.socks_proxy_port > 0:
                    return self.socks_proxy_port
                else :
                    return self.default_socks_proxy_port

        class Policy:
            class Type(Enum):
                ip = auto()
                domain = auto()
            class Outbound(Enum):
                direct = auto()
                proxy = auto()
                block = auto()

            def __init__(self):
                self.contents:List[str] = []
                self.type:str = ''
                self.outbound:str = ''
                self.enable = True

        class DnsConfig:
            def __init__(self):
                self.default_local = '119.29.29.29'
                self.default_remote = '8.8.8.8'
                self.local = ''
                self.remote = ''

            def local_dns(self) -> str:
                if len(self.local):
                    return self.local
                else:
                    return self.default_local

            def remote_dns(self) -> str:
                if len(self.remote):
                    return self.remote
                else:
                    return self.default_remote
        class AutoDetectAndSwitch:
            def __init__(self):
                self.enabled = False
                self.detect_span = 60
                self.detect_url = 'https://github.com/'
                self.failed_count = 3
                self.timeout = 1.0
                self.last_switch_time = ''

        class GeoData:
            def __init__(self):
                self.check_url = 'https://github.com/Loyalsoldier/v2ray-rules-dat/releases'
                self.current_version = ''

        def __init__(self):
            self.log: V2RayUserConfig.AdvanceConfig.Log = V2RayUserConfig.AdvanceConfig.Log()
            self.inbound : V2RayUserConfig.AdvanceConfig.InBound = V2RayUserConfig.AdvanceConfig.InBound()
            self.dns: V2RayUserConfig.AdvanceConfig.DnsConfig = V2RayUserConfig.AdvanceConfig.DnsConfig()
            self.policys:List[V2RayUserConfig.AdvanceConfig.Policy] = []
            self.auto_detect: V2RayUserConfig.AdvanceConfig.AutoDetectAndSwitch = V2RayUserConfig.AdvanceConfig.AutoDetectAndSwitch()
            self.geo_data:V2RayUserConfig.AdvanceConfig.GeoData = V2RayUserConfig.AdvanceConfig.GeoData()
            self.proxy_preferred = True
            self.enable_mux = True
            self.block_ad = True

    def filename(self):
        return 'config/v2ray_user_config.json'

    def __init__(self):
        self.proxy_mode:int = self.ProxyMode.ProxyAuto.value
        self.node:Node = Node()
        self.advance_config:V2RayUserConfig.AdvanceConfig = self.AdvanceConfig()