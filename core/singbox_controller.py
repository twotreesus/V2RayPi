# encoding: utf-8
import json
import os
import platform
import shutil
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
        if sys.platform == 'darwin':
            result = subprocess.run(
                ['brew', 'services', 'list'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
            )
            for line in result.stdout.splitlines():
                if line.startswith('sing-box') and 'started' in line:
                    return True
            return False
        result = subprocess.run(
            ['systemctl', 'is-active', 'sing-box'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
        )
        return result.stdout.strip() == 'active'

    def version(self) -> str:
        try:
            ver = subprocess.check_output(
                "sing-box version 2>/dev/null | head -n 1 | awk '{print $NF}'",
                shell=True
            ).decode('utf-8').strip()
            return ver if ver.startswith('v') else 'v' + ver
        except Exception:
            return ''

    def check_new_version(self) -> str:
        r = requests.get('https://api.github.com/repos/SagerNet/sing-box/releases/latest')
        return r.json().get('tag_name', '')

    def update(self) -> bool:
        was_running = self.running()
        result = subprocess.run(
            'curl -fsSL https://sing-box.app/install.sh | sh',
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            return False
        if was_running:
            self._service('restart')
        return True

    def _binary(self) -> str:
        if sys.platform == 'darwin':
            candidates = ['/opt/homebrew/bin/sing-box', '/usr/local/bin/sing-box']
        else:
            candidates = ['/usr/local/bin/sing-box', '/usr/bin/sing-box', '/usr/local/sbin/sing-box']
        for p in candidates:
            if os.path.exists(p):
                return p
        return shutil.which('sing-box') or 'sing-box'

    def _service(self, action: str) -> bool:
        if sys.platform == 'darwin':
            cmd = ['brew', 'services', action, 'sing-box']
        else:
            cmd = ['systemctl', action, 'sing-box']
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0

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
