# encoding: utf-8
"""Process and configuration control for the mihomo core."""
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

from typing import List

import requests
import yaml

from .mihomo_user_config import MihomoUserConfig
from .mihomo_config import CONTROLLER_LISTEN, CONTROLLER_PORT, MihomoConfig
from .mihomo_default_path import MihomoDefaultPath
from .node import Node

SERVICE_NAME = 'mihomo'
IPTABLE_SERVICE_NAME = 'mihomo_iptable.service'

API_BASE_URL = 'http://{0}:{1}'.format(CONTROLLER_LISTEN, CONTROLLER_PORT)
API_CONNECT_TIMEOUT = 3
# Reloading re-reads the geo databases, which is slow on a small SBC but still
# an order of magnitude cheaper than a full process restart.
API_RELOAD_TIMEOUT = 60
API_SECRET_BYTES = 16


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

    def running(self) -> bool:
        # Exact process-name match only.  A loose `ps | grep mihomo` false-positives
        # on installers whose argv still contains `--branch feat/mihomo`.
        try:
            result = subprocess.run(
                ['pgrep', '-x', SERVICE_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return result.returncode == 0

    def service_available(self) -> bool:
        try:
            result = subprocess.run(
                ['systemctl', 'cat', '{0}.service'.format(SERVICE_NAME)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return False
        return result.returncode == 0

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
        match = re.search(
            r'\bv?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b',
            result.stdout,
        )
        if match:
            return 'v' + match.group(1)
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
        # The running core still authenticates with the secret from the config it
        # was started with, so the current one has to be carried over instead of
        # minted again on every node application.
        api_secret = self.api_secret() or secrets.token_hex(API_SECRET_BYTES)
        config = MihomoConfig.gen_config(
            user_config, all_nodes, subscribe_hosts,
            controller_secret=api_secret,
        )
        return self.apply_config(config, api_secret)

    def apply_config(self, config: str, api_secret: str = '') -> bool:
        if not self.test_config(config):
            return False

        config_file = MihomoDefaultPath.config_file()
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w+') as f:
            f.write(config)

        # Loading the new config into the running core skips the systemd stop /
        # start and the process bootstrap.  A core that predates the control API,
        # or one that is not running, still needs the restart.
        if api_secret and self.reload_config(api_secret):
            return True
        return self.restart()

    def api_secret(self) -> str:
        """Control API secret of the currently running core."""
        try:
            with open(MihomoDefaultPath.config_file(), 'r') as f:
                config = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as error:
            print('Could not read the mihomo config for its API secret: {0}'.format(error))
            return ''
        if not isinstance(config, dict):
            return ''
        secret = config.get('secret')
        return secret if isinstance(secret, str) else ''

    def reload_config(self, api_secret: str) -> bool:
        if not self.running():
            return False

        # force=true keeps the reload equivalent to the restart it replaces:
        # listeners are rebuilt, so an inbound port change also takes effect.
        url = '{0}/configs?force=true'.format(API_BASE_URL)
        try:
            response = requests.put(
                url,
                json={'path': MihomoDefaultPath.config_file()},
                headers={'Authorization': 'Bearer {0}'.format(api_secret)},
                timeout=(API_CONNECT_TIMEOUT, API_RELOAD_TIMEOUT),
            )
        except requests.RequestException as error:
            print('mihomo config reload over the control API failed: {0}'.format(error))
            return False

        if response.status_code // 100 == 2:
            print('Reloaded the mihomo config through the control API')
            return True
        print('mihomo refused the config reload: HTTP {0} {1}'.format(
            response.status_code, response.text.strip(),
        ))
        return False

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
        response = requests.head(url + '/latest', allow_redirects=False, timeout=30)
        response.raise_for_status()
        dest_url = response.headers['location']
        version = dest_url.split('/')[-1]
        return version

    def update_geo_data(self, url):
        # Fresh installs download GEO before the systemd unit exists.  Only
        # bounce a live, managed core; the next start picks up the new files.
        should_restart = self.running() and self.service_available()
        asset_path = MihomoDefaultPath.asset_path()
        os.makedirs(asset_path, exist_ok=True)

        temporary_files = []
        try:
            for filename in ('geoip.dat', 'geosite.dat'):
                response = requests.get(
                    url + '/latest/download/' + filename,
                    stream=True, timeout=60,
                )
                response.raise_for_status()
                total = int(response.headers.get('content-length', 0))
                downloaded = 0
                print('Downloading {0}...'.format(filename), flush=True)
                with tempfile.NamedTemporaryFile(
                    mode='wb', dir=asset_path, prefix=filename + '.',
                    suffix='.tmp', delete=False,
                ) as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        output.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            progress = downloaded * 100 // total
                            print(
                                '\rDownloading {0}: {1}% ({2}/{3} MiB)'.format(
                                    filename, progress,
                                    downloaded // (1024 * 1024),
                                    total // (1024 * 1024),
                                ),
                                end='', flush=True,
                            )
                    if total:
                        print()
                    if output.tell() == 0:
                        raise ValueError('Downloaded {0} is empty'.format(filename))
                print('Downloaded {0} ({1} MiB)'.format(
                    filename, downloaded // (1024 * 1024),
                ), flush=True)
                temporary_files.append((output.name, asset_path + filename))

            for source, destination in temporary_files:
                os.replace(source, destination)
            temporary_files = []
        finally:
            for source, _ in temporary_files:
                try:
                    os.unlink(source)
                except OSError:
                    pass

        if should_restart:
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

    def service_available(self) -> bool:
        # Homebrew formula install is enough; install_osx starts the service
        # before the first GEO download.
        return shutil.which(SERVICE_NAME) is not None or os.path.isfile(self._binary())

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
