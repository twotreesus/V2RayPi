# encoding: utf-8
"""Resolve the current egress IP via the ipinfo CLI."""
import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, Optional


class EgressIpResolver:
    TTL_SECONDS = 300

    def __init__(self, token_provider=None):
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None
        self._fetched_at = 0.0
        self._token_provider = token_provider

    def _binary(self) -> str:
        return os.environ.get('IPINFO_BIN') or shutil.which('ipinfo') or 'ipinfo'

    def _token(self) -> str:
        token = ''
        if self._token_provider:
            token = self._token_provider() or ''
        if not token:
            token = os.environ.get('IPINFO_TOKEN') or ''
        return str(token).strip()

    def get(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            if (
                not force
                and self._cache is not None
                and now - self._fetched_at < self.TTL_SECONDS
            ):
                return dict(self._cache)

        info = self._query()
        with self._lock:
            self._cache = info
            self._fetched_at = time.time()
            return dict(info)

    def update_cache(self, info: Dict[str, Any]) -> None:
        with self._lock:
            if self._cache is None:
                return
            self._cache = dict(info)

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._fetched_at = 0.0

    def _query(self) -> Dict[str, Any]:
        binary = self._binary()
        token = self._token()
        command = [binary, 'myip', '--json', '--nocache', '--nocolor']
        if token:
            command.extend(['--token', token])
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                env=self._subprocess_env(token),
            )
        except FileNotFoundError:
            print('ipinfo binary not found; egress IP lookup skipped')
            return self._failure('ipinfo_missing')
        except subprocess.TimeoutExpired:
            print('ipinfo myip timed out')
            return self._failure('ipinfo_timeout')
        except OSError as e:
            print(f'ipinfo myip failed to start: {e}')
            return self._failure('ipinfo_failed')

        if result.returncode != 0:
            err = (result.stderr or result.stdout or '').strip()
            print(f'ipinfo myip returned {result.returncode}: {err}')
            if self._is_rate_limited(err):
                return self._failure('ipinfo_rate_limited')
            return self._failure('ipinfo_failed')

        try:
            payload = json.loads(result.stdout or '{}')
        except json.JSONDecodeError:
            print('ipinfo myip returned non-JSON output')
            return self._failure('ipinfo_invalid')

        if not isinstance(payload, dict):
            return self._failure('ipinfo_invalid')

        ip = str(payload.get('ip') or '').strip()
        if not ip:
            return self._failure('ipinfo_empty')

        city = str(payload.get('city') or '').strip()
        region = str(payload.get('region') or '').strip()
        country = str(payload.get('country') or '').strip()
        org = str(payload.get('org') or '').strip()
        location = ', '.join([part for part in (city, region, country) if part])
        summary_parts = [ip]
        if location:
            summary_parts.append(location)
        if org:
            summary_parts.append(org)

        return {
            'ok': True,
            'ip': ip,
            'city': city,
            'region': region,
            'country': country,
            'org': org,
            'summary': ' · '.join(summary_parts),
            'error': '',
        }

    def _subprocess_env(self, token: str = '') -> Dict[str, str]:
        # Avoid noisy config-file warnings when the service home is not writable.
        env = os.environ.copy()
        env.setdefault('XDG_CONFIG_HOME', '/tmp')
        env.setdefault('HOME', env.get('HOME') or '/tmp')
        if token:
            env['IPINFO_TOKEN'] = token
        else:
            env.pop('IPINFO_TOKEN', None)
        return env

    def _is_rate_limited(self, err: str) -> bool:
        text = (err or '').lower()
        return '429' in text or 'daily limit' in text or 'rate limit' in text

    def _failure(self, error: str) -> Dict[str, Any]:
        return {
            'ok': False,
            'ip': '',
            'city': '',
            'region': '',
            'country': '',
            'org': '',
            'summary': '',
            'error': error,
        }
