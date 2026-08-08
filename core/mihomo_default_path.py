# encoding: utf-8
import sys
import platform

class MihomoDefaultPath:
    @classmethod
    def config_dir(cls) -> str:
        if sys.platform == 'darwin':
            if platform.machine() == 'arm64':
                return '/opt/homebrew/etc/mihomo/'
            else:
                return '/usr/local/etc/mihomo/'
        else:
            return '/etc/mihomo/'

    @classmethod
    def config_file(cls) -> str:
        return cls.config_dir() + 'config.yaml'

    @classmethod
    def log_file(cls) -> str:
        if sys.platform == 'darwin':
            if platform.machine() == 'arm64':
                return '/opt/homebrew/var/log/mihomo.log'
            else:
                return '/usr/local/var/log/mihomo.log'
        else:
            return '/var/log/mihomo/mihomo.log'

    @classmethod
    def asset_path(cls) -> str:
        # mihomo reads geoip.dat / geosite.dat from the working directory
        # passed to it via `-d`, which is the config directory.
        return cls.config_dir()
