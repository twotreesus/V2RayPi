# encoding: utf-8
import sys
import platform
from os import path
class V2rayDefaultPath:
    @classmethod
    def access_log(cls) -> str:
        if sys.platform == 'darwin':
            return path.expanduser('~/Library/Logs/xray/access.log')
        else:
            return '/var/log/xray/access.log'

    @classmethod
    def error_log(cls) -> str:
        if sys.platform == 'darwin':
            return path.expanduser('~/Library/Logs/xray/error.log')
        else:
            return '/var/log/xray/error.log'

    @classmethod
    def config_file(cls) -> str:
        if sys.platform == 'darwin':
            if platform.machine() == 'arm64':
                return '/opt/homebrew/etc/xray/config.json'
            else:
                return '/usr/local/etc/xray/config.json'
        else:
            return '/usr/local/etc/xray/config.json'

    @classmethod
    def asset_path(cls) -> str:
        if sys.platform == 'darwin':
            if platform.machine() == 'arm64':
                return '/opt/homebrew/share/xray/'
            else:
                return '/usr/local/share/xray/'
        else:
            return '/usr/local/share/xray/'