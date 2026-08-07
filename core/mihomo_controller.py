# encoding: utf-8
"""Process and configuration control for the mihomo core."""
import os
import shutil
import subprocess
import sys
import tempfile

from typing import List

import requests

from .mihomo_user_config import MihomoUserConfig
from .mihomo_config import MihomoConfig
from .mihomo_default_path import MihomoDefaultPath
from .node import Node

SERVICE_NAME = 'mihomo'
IPTABLE_SERVICE_NAME = 'mihomo_iptable.service'


class MihomoController:
    def _binary(self) -> str:
        return os.environ.get('MIHOMO_BIN') or shutil.which('mihomo') or 'mihomo'

    def start(self) -> bool:
        cmd = "systemctl start {0}.service".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return self.running()

    def stop(self) -> bool:
        cmd = "systemctl stop {0}.service".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return not self.running()

    def restart(self) -> bool:
        cmd = "systemctl restart {0}.service".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return self.running()

    def reload(self) -> bool:
        # The service unit maps reload onto SIGHUP, which mihomo uses to re-read
        # its configuration without dropping established connections.
        result = subprocess.run(
            "systemctl reload {0}.service".format(SERVICE_NAME),
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print('mihomo reload failed, falling back to restart: {0}'.format(
                result.stdout.decode('utf-8').strip()))
            return False
        return self.running()

    def running(self) -> bool:
        cmd = """ps -ef | grep "mihomo" | grep -v grep | awk '{print $2}'"""
        output = subprocess.check_output(cmd, shell=True).decode('utf-8')
        return output.strip() != ''

    def version(self) -> str:
        try:
            result = subprocess.run(
                [self._binary(), '-v'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        except OSError:
            return ''
        if result.returncode != 0:
            return ''
        # `mihomo -v` prints e.g. "Mihomo Meta v1.19.29 linux arm64 with go1.24".
        for token in result.stdout.split():
            if token.startswith('v') and any(char.isdigit() for char in token):
                return token
        return ''

    def check_new_version(self) -> str:
        r = requests.get('https://api.github.com/repos/MetaCubeX/mihomo/releases/latest')
        return r.json()['tag_name']

    def update(self) -> bool:
        was_running = self.running()
        result = subprocess.run(
            "bash ./script/update_mihomo.sh update",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = result.stdout.decode('utf-8')
        print('mihomo update output:\n{0}'.format(output))
        if result.returncode != 0:
            return False
        if was_running:
            self.restart()
        return True

    def log(self) -> str:
        lines = self.tailf(MihomoDefaultPath.log_file(), 10)
        return lines.replace('\n', '<br>')

    def tailf(self, file, count) -> str:
        lines = subprocess.check_output("tail -n {0} {1}".format(count, file), shell=True).decode('utf-8')
        return lines

    def apply_node(self, user_config: MihomoUserConfig, all_nodes: List[Node],
                   subscribe_hosts: List[str] = None) -> bool:
        config = MihomoConfig.gen_config(user_config, all_nodes, subscribe_hosts)
        return self.apply_config(config)

    def apply_config(self, config: str) -> bool:
        if not self.test_config(config):
            return False

        config_file = MihomoDefaultPath.config_file()
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w+') as f:
            f.write(config)

        if self.reload():
            return True
        return self.restart()

    def test_config(self, config: str) -> bool:
        """Validate a config before it replaces the running one.

        Writing an invalid config and reloading would leave the side-router
        without a working proxy, so the candidate is checked first.  `-d` points
        at the live config directory on purpose: mihomo downloads geoip.dat and
        geosite.dat into that directory when they are missing, and a throwaway
        directory would re-download ~27MB on every node application.  Only `-f`
        points at the candidate, so the running config.yaml is left alone.

        A mihomo build without `-t` support is treated as a pass rather than
        blocking every node application.
        """
        config_dir = MihomoDefaultPath.config_dir()
        os.makedirs(config_dir, exist_ok=True)
        handle, candidate = tempfile.mkstemp(prefix='mihomo_candidate_', suffix='.yaml')
        try:
            with os.fdopen(handle, 'w') as f:
                f.write(config)
            result = subprocess.run(
                [self._binary(), '-t', '-d', config_dir, '-f', candidate],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if result.returncode == 0:
                return True
            output = result.stdout.strip()
            if 'flag provided but not defined' in output or 'Usage of' in output:
                print('mihomo does not support -t, skipping config validation')
                return True
            print('mihomo rejected the generated config:\n{0}'.format(output))
            return False
        except OSError as error:
            print('Could not validate the generated config: {0}'.format(error))
            return True
        finally:
            try:
                os.unlink(candidate)
            except OSError:
                pass

    @staticmethod
    def _iptables_service_state(action):
        result = subprocess.run(
            ["systemctl", action, "--quiet", IPTABLE_SERVICE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def enable_iptables(self):
        # The service is intentionally disabled on a fresh installation.  Once
        # a node has been applied successfully, enable it and make sure the
        # current boot has the rules as well.  This method is idempotent and is
        # called for every successful node application.
        if self._iptables_service_state("is-enabled"):
            if not self._iptables_service_state("is-active"):
                subprocess.check_output("systemctl start {0}".format(IPTABLE_SERVICE_NAME), shell=True)
            return True
        subprocess.check_output("bash ./script/config_iptable.sh", shell=True)
        subprocess.check_output("systemctl enable {0}".format(IPTABLE_SERVICE_NAME), shell=True)
        return True

    def check_new_geo_data(self, url) -> str:
        headers = requests.head(url + '/latest').headers
        dest_url = headers['location']
        version = dest_url.split('/')[-1]
        return version

    def update_geo_data(self, url):
        geoip_url = url + '/latest/download/geoip.dat'
        r = requests.get(geoip_url)
        geoip = ''
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(r.content)
            geoip = f.name

        geosite_url = url + '/latest/download/geosite.dat'
        r = requests.get(geosite_url)
        geosite = ''
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(r.content)
            geosite = f.name

        asset_path = MihomoDefaultPath.asset_path()
        os.makedirs(asset_path, exist_ok=True)
        shutil.move(geoip, asset_path + 'geoip.dat')
        shutil.move(geosite, asset_path + 'geosite.dat')

        self.restart()


class MacOSMihomoController(MihomoController):
    def start(self) -> bool:
        cmd = "brew services start {0}".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return self.running()

    def stop(self) -> bool:
        cmd = "brew services stop {0}".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return not self.running()

    def restart(self) -> bool:
        cmd = "brew services restart {0}".format(SERVICE_NAME)
        subprocess.check_output(cmd, shell=True).decode('utf-8')
        return self.running()

    def reload(self) -> bool:
        # brew services has no reload verb.
        return False

    def update(self) -> bool:
        was_running = self.running()
        result = subprocess.run(
            "brew upgrade mihomo",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        output = result.stdout.decode('utf-8')
        print('mihomo update output:\n{0}'.format(output))
        if result.returncode != 0:
            return False
        if was_running:
            self.restart()
        return True

    def enable_iptables(self):
        return


def make_controller():
    if sys.platform == 'darwin':
        return MacOSMihomoController()
    else:
        return MihomoController()
