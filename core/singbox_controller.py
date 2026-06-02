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
        if node.protocol == 'hysteria2':
            outbound = self._gen_hysteria2_outbound(node)
        else:
            outbound = self._gen_anytls_outbound(node)

        return {
            'inbounds': [
                {
                    'type': 'socks',
                    'tag': 'socks-in',
                    'listen': '127.0.0.1',
                    'listen_port': SINGBOX_SOCKS_PORT,
                }
            ],
            'outbounds': [outbound],
        }

    def _gen_anytls_outbound(self, node) -> dict:
        outbound = {
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
            outbound['routing_mark'] = 255

        return outbound

    def _gen_hysteria2_outbound(self, node) -> dict:
        outbound = {
            'type': 'hysteria2',
            'tag': 'proxy',
            'server': node.add,
            'server_port': int(node.port or 443),
            'password': node.password or '',
            'tls': {
                'enabled': True,
                'server_name': node.sni or node.add,
                'insecure': getattr(node, 'skip_cert_verify', False),
            },
        }

        if getattr(node, 'alpn', None):
            outbound['tls']['alpn'] = node.alpn if isinstance(node.alpn, list) else [node.alpn]
        if getattr(node, 'obfs', None):
            outbound['obfs'] = {
                'type': node.obfs,
                'password': getattr(node, 'obfs_password', None) or '',
            }
        up_mbps = self._mbps_value(getattr(node, 'up', None))
        if up_mbps:
            outbound['up_mbps'] = up_mbps
        down_mbps = self._mbps_value(getattr(node, 'down', None))
        if down_mbps:
            outbound['down_mbps'] = down_mbps
        if getattr(node, 'ports', None):
            outbound['server_ports'] = node.ports
        if getattr(node, 'hop_interval', None):
            outbound['hop_interval'] = node.hop_interval
        if sys.platform != 'darwin':
            outbound['routing_mark'] = 255

        return outbound

    def _mbps_value(self, value):
        if value is None or value == '':
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip().split()[0]
        try:
            return int(float(text))
        except ValueError:
            return None
