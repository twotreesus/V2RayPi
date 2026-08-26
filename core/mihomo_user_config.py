# encoding: utf-8
from enum import Enum, auto
from typing import List
from .base_data_item import BaseDataItem
from .node import Node

class MihomoUserConfig(BaseDataItem):
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
            LATENCY_PROBE_URL = 'https://www.gstatic.com/generate_204'
            DETECT_SPAN = 300
            FAILED_COUNT = 3
            TIMEOUT = 2.0

            def __init__(self):
                self.enabled = False
                self.detect_span = self.DETECT_SPAN
                self.detect_url = self.LATENCY_PROBE_URL
                self.failed_count = self.FAILED_COUNT
                self.timeout = self.TIMEOUT
                self.last_switch_time = ''
                self.last_probe_time = ''
                self.last_probe_ok = True
                self.last_probe_delay_ms = 0

            def apply_fixed_defaults(self) -> None:
                self.detect_span = self.DETECT_SPAN
                self.failed_count = self.FAILED_COUNT
                self.timeout = self.TIMEOUT

        class GeoData:
            def __init__(self):
                self.check_url = 'https://github.com/Loyalsoldier/v2ray-rules-dat/releases'
                self.current_version = ''

            def enabled(self) -> bool:
                return self.current_version != ''

        def __init__(self):
            self.log: MihomoUserConfig.AdvanceConfig.Log = MihomoUserConfig.AdvanceConfig.Log()
            self.inbound : MihomoUserConfig.AdvanceConfig.InBound = MihomoUserConfig.AdvanceConfig.InBound()
            self.dns: MihomoUserConfig.AdvanceConfig.DnsConfig = MihomoUserConfig.AdvanceConfig.DnsConfig()
            self.policys:List[MihomoUserConfig.AdvanceConfig.Policy] = []
            self.auto_detect: MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
            self.geo_data:MihomoUserConfig.AdvanceConfig.GeoData = MihomoUserConfig.AdvanceConfig.GeoData()
            self.proxy_preferred = True
            self.enable_mux = True
            self.block_ad = True

    def filename(self):
        return 'config/mihomo_user_config.json'

    def __init__(self):
        self.proxy_mode:int = self.ProxyMode.ProxyAuto.value
        self.node:Node = Node()
        self.advance_config:MihomoUserConfig.AdvanceConfig = self.AdvanceConfig()
        self.ipinfo_token = ''
