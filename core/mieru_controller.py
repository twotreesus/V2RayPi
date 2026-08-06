# encoding: utf-8
"""Controller for the native Mieru client sidecar.

Mieru is deliberately kept outside Xray.  The client exposes a local SOCKS5
listener and Xray uses that listener as its proxy outbound, just like the
existing sing-box sidecar path.
"""
import ipaddress
import json
import os
import signal
import shutil
import subprocess
import time
from typing import Optional

import requests

MIERU_SOCKS_PORT = int(os.environ.get('MIERU_SOCKS_PORT', '2335'))
MIERU_RPC_PORT = int(os.environ.get('MIERU_RPC_PORT', '2336'))
MIERU_KILL_WAIT_TIMEOUT = float(os.environ.get('MIERU_KILL_WAIT_TIMEOUT', '3'))

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIERU_CONFIG_PATH = os.environ.get(
    'MIERU_CONFIG_PATH',
    os.path.join(_PROJECT_DIR, 'config', 'mieru_client_config.json'),
)


class MieruController:
    """Small process wrapper around the native ``mieru`` CLI."""

    def __init__(self, binary: Optional[str] = None, config_path: Optional[str] = None):
        self.binary = binary or os.environ.get('MIERU_BIN') or shutil.which('mieru') or 'mieru'
        self.config_path = config_path or MIERU_CONFIG_PATH

    def apply_node(self, node) -> bool:
        config = self._gen_config(node)
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        try:
            # `mieru apply config` only updates the on-disk configuration. It
            # does not reload the already-running client's mux, so an active
            # daemon must be restarted for a node switch to take effect. This
            # only restarts Mieru when applying a Mieru node; other sidecars
            # are intentionally left idle by V2RayController.
            self._run('apply', 'config', self.config_path, check=True)
            if self.running() and not self.stop():
                return False
            result = self._run('start', check=True)
            return result.returncode == 0 and self._wait_for_running(True)
        except (OSError, subprocess.SubprocessError):
            return False

    def stop(self) -> bool:
        # Mieru's RPC stop command can time out while leaving the daemon alive.
        # Node switching needs a deterministic teardown, so terminate the
        # sidecar directly instead of relying on that RPC path.
        pids = self._pids()
        if not pids:
            return True
        self._signal_pids(pids, signal.SIGKILL)
        return self._wait_for_running(False, timeout=MIERU_KILL_WAIT_TIMEOUT)

    @staticmethod
    def _signal_pids(pids, sig) -> bool:
        success = True
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                continue
            except OSError:
                success = False
        return success

    def _wait_for_running(self, expected: bool, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.running() == expected:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def _pids(self):
        try:
            process_name = os.path.basename(self.binary)
            result = subprocess.run(
                ['pgrep', '-x', process_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return []
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.splitlines():
            try:
                pids.append(int(line.strip()))
            except (TypeError, ValueError):
                continue
        return pids

    def running(self) -> bool:
        return bool(self._pids())

    def version(self) -> str:
        try:
            result = self._run('version')
            if result.returncode == 0:
                version = result.stdout.strip().splitlines()[0]
                return version if version.startswith('v') else 'v' + version
        except OSError:
            pass
        return ''

    def check_new_version(self) -> str:
        """Return the latest official Mieru release tag."""
        response = requests.get(
            'https://api.github.com/repos/enfein/mieru/releases/latest',
            timeout=10,
        )
        response.raise_for_status()
        tag = response.json()['tag_name']
        return tag if tag.startswith('v') else 'v' + tag

    def update(self) -> bool:
        """Install the latest Mieru binary without touching the sidecar process.

        The installer replaces only the executable.  A running native client is
        intentionally left alone; the new binary will be used on its next
        start, matching the sidecar lifecycle policy used by V2RayPi.
        """
        script_path = os.path.join(_PROJECT_DIR, 'script', 'update_mieru.sh')
        if not os.path.isfile(script_path):
            return False
        try:
            result = subprocess.run(
                ['bash', script_path, 'update'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy(),
            )
        except OSError:
            return False
        return result.returncode == 0

    def _run(self, *args, check=False):
        command = [self.binary, *args]
        kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
            'text': True,
            'check': check,
        }
        if args and args[0] == 'start':
            # `mieru start` daemonizes by launching `mieru run` and then
            # returning without waiting for that child.  If the child inherits
            # the stdout=PIPE used by subprocess.run, communicate() waits for
            # EOF forever because the daemon keeps the pipe open.  Detach the
            # daemon's stdio so we only wait for the short-lived start command.
            kwargs.update({
                'stdin': subprocess.DEVNULL,
                'stdout': subprocess.DEVNULL,
                'stderr': subprocess.DEVNULL,
                'start_new_session': True,
            })
        return subprocess.run(command, **kwargs)

    @classmethod
    def _port_binding(cls, binding, default_port):
        if not isinstance(binding, dict):
            binding = {'port': binding}
        port_range = binding.get('portRange') or binding.get('port-range') or binding.get('port_range')
        if port_range:
            return {
                'portRange': str(port_range),
                'protocol': str(binding.get('protocol') or 'TCP').upper(),
            }
        port = binding.get('port', default_port)
        try:
            port = int(port)
        except (TypeError, ValueError):
            # The native client expects a numeric binding.  Invalid optional
            # bindings are ignored by _gen_config instead of producing a
            # config that cannot be applied.
            return None
        return {
            'port': port,
            'protocol': str(binding.get('protocol') or 'TCP').upper(),
        }

    def _gen_config(self, node) -> dict:
        bindings = []
        for binding in (getattr(node, 'port_bindings', None) or []):
            parsed = self._port_binding(binding, getattr(node, 'port', None))
            if parsed:
                bindings.append(parsed)
        if not bindings:
            parsed = self._port_binding(
                {'port': getattr(node, 'port', None), 'protocol': 'TCP'},
                getattr(node, 'port', 443) or 443,
            )
            if parsed:
                bindings.append(parsed)

        server = {'portBindings': bindings}
        address = getattr(node, 'add', None)
        if address:
            address = str(address).strip().strip('[]')
            try:
                # Mieru validates ipAddress as a literal IPv4/IPv6 address.
                # Clash's `server` is commonly a hostname, so emit that as
                # domainName instead of placing a DNS name in ipAddress.
                ipaddress.ip_address(address)
                server['ipAddress'] = address
            except ValueError:
                server['domainName'] = address

        # Keep an explicitly supplied domain name (or SNI) as the Mieru
        # domainName field.  Mieru ignores ipAddress when domainName is set.
        domain_name = getattr(node, 'domain_name', None) or getattr(node, 'sni', None)
        if domain_name:
            server['domainName'] = domain_name

        profile = {
            'profileName': getattr(node, 'profile_name', None) or 'v2raypi',
            'user': {
                'name': getattr(node, 'username', None) or '',
                'password': getattr(node, 'password', None) or '',
            },
            'servers': [server],
        }

        # These are optional flat Node fields.  Do not emit null values: older
        # mieru clients reject unknown/empty profile options more often than
        # they reject an omitted option.
        optional_fields = {
            'mtu': self._int_value(getattr(node, 'mtu', None)),
            'multiplexing': getattr(node, 'multiplexing', None),
            'handshakeMode': getattr(node, 'handshake_mode', None),
            'trafficPattern': getattr(node, 'traffic_pattern', None),
        }
        for key, value in optional_fields.items():
            if key == 'multiplexing' and isinstance(value, str):
                value = {'level': value}
            if value not in (None, '') and (key != 'trafficPattern' or isinstance(value, dict)):
                profile[key] = value

        return {
            'rpcPort': MIERU_RPC_PORT,
            'socks5Port': MIERU_SOCKS_PORT,
            'activeProfile': getattr(node, 'profile_name', None) or 'v2raypi',
            'profiles': [profile],
        }

    @staticmethod
    def _int_value(value):
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
