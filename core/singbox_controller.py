# encoding: utf-8
import json
import os
import platform
import subprocess
import sys
import requests

SINGBOX_SOCKS_PORT = 2334

if sys.platform == 'darwin':
    _SINGBOX_CONFIG_PATH = (
        '/opt/homebrew/etc/sing-box/config.json'
        if platform.machine() == 'arm64'
        else '/usr/local/etc/sing-box/config.json'
    )
else:
    _SINGBOX_CONFIG_PATH = '/etc/sing-box/config.json'


class SingboxController:
    def apply_node(self, node) -> bool:
        config = self._gen_config(node)
        os.makedirs(os.path.dirname(_SINGBOX_CONFIG_PATH), exist_ok=True)
        with open(_SINGBOX_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
        self._service('enable')
        return self._service('restart')

    def stop(self) -> bool:
        self._service('stop')
        self._service('disable')
        return True

    def running(self) -> bool:
        cmd = """ps -ef | grep "sing-box" | grep -v grep | awk '{print $2}'"""
        output = subprocess.check_output(cmd, shell=True).decode('utf-8')
        return output.strip() != ''

    def version(self) -> str:
        ver = subprocess.check_output(
            "echo `sing-box version 2>/dev/null | head -n 1` | awk '{print $3}'",
            shell=True
        ).decode('utf-8').strip()
        return ver if ver.startswith('v') else 'v' + ver

    def check_new_version(self) -> str:
        r = requests.get('https://api.github.com/repos/SagerNet/sing-box/releases/latest')
        return r.json()['tag_name']

    def update(self) -> bool:
        was_running = self.running()
        if sys.platform == 'darwin':
            result = subprocess.run(
                'brew upgrade sing-box',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=os.environ.copy()
            )
        else:
            result = subprocess.run(
                'curl -fsSL https://sing-box.app/install.sh | sh',
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=os.environ.copy()
            )
        output = result.stdout.decode('utf-8')
        if output.find('Setting up sing-box') != -1 or output.find('/Cellar/sing-box/') != -1:
            if was_running:
                self._service('restart')
            return True
        return False

    def _service(self, action: str) -> bool:
        if sys.platform == 'darwin':
            cmd = 'brew services {} sing-box'.format(action)
        else:
            cmd = 'systemctl {} sing-box'.format(action)
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = result.stdout.decode('utf-8')
        return output.find('Failed') == -1

    def _gen_config(self, node) -> dict:
        anytls_outbound = {
            'type': 'anytls',
            'tag': 'proxy',
            'server': node.add,
            'server_port': int(node.port),
            'password': node.password or '',
            'tls': {
                'enabled': True,
                'server_name': node.sni or node.add,
                'insecure': getattr(node, 'skip_cert_verify', False),
            },
        }
        if sys.platform != 'darwin':
            anytls_outbound['routing_mark'] = 255

        return {
            'inbounds': [
                {
                    'type': 'socks',
                    'tag': 'socks-in',
                    'listen': '127.0.0.1',
                    'listen_port': SINGBOX_SOCKS_PORT,
                }
            ],
            'outbounds': [anytls_outbound],
        }
