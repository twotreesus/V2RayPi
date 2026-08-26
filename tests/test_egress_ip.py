import json
import unittest
from unittest.mock import Mock, patch

from core.egress_ip import EgressIpResolver


class EgressIpResolverTest(unittest.TestCase):
    def test_parses_ipinfo_json_into_summary(self):
        resolver = EgressIpResolver()
        payload = {
            'ip': '203.0.113.10',
            'city': 'Hong Kong',
            'region': 'Hong Kong',
            'country': 'HK',
            'org': 'AS3491 PCCW Global',
        }
        completed = Mock(
            returncode=0,
            stdout=json.dumps(payload),
            stderr='',
        )

        with patch('core.egress_ip.subprocess.run', return_value=completed):
            info = resolver.get(force=True)

        self.assertTrue(info['ok'])
        self.assertEqual(info['ip'], '203.0.113.10')
        self.assertEqual(
            info['summary'],
            '203.0.113.10 · Hong Kong, Hong Kong, HK · AS3491 PCCW Global',
        )

    def test_uses_cache_within_ttl(self):
        resolver = EgressIpResolver()
        completed = Mock(
            returncode=0,
            stdout=json.dumps({'ip': '198.51.100.1', 'country': 'US'}),
            stderr='',
        )

        with patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ) as run:
            first = resolver.get(force=True)
            second = resolver.get()

        self.assertEqual(run.call_count, 1)
        self.assertEqual(first['ip'], second['ip'])

    def test_invalidate_clears_cache(self):
        resolver = EgressIpResolver()
        completed = Mock(
            returncode=0,
            stdout=json.dumps({'ip': '198.51.100.1', 'country': 'US'}),
            stderr='',
        )

        with patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ) as run:
            resolver.get(force=True)
            resolver.invalidate()
            resolver.get()

        self.assertEqual(run.call_count, 2)

    def test_missing_binary_returns_error(self):
        resolver = EgressIpResolver()
        with patch(
            'core.egress_ip.subprocess.run',
            side_effect=FileNotFoundError(),
        ):
            info = resolver.get(force=True)

        self.assertFalse(info['ok'])
        self.assertEqual(info['error'], 'ipinfo_missing')

    def test_update_cache_keeps_ttl_and_extra_fields(self):
        resolver = EgressIpResolver()
        completed = Mock(
            returncode=0,
            stdout=json.dumps({'ip': '198.51.100.1', 'country': 'US'}),
            stderr='',
        )

        with patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ) as run:
            first = resolver.get(force=True)
            first['latency_ms'] = 128
            resolver.update_cache(first)
            second = resolver.get()

        self.assertEqual(run.call_count, 1)
        self.assertEqual(second['latency_ms'], 128)

    def test_passes_token_to_ipinfo(self):
        resolver = EgressIpResolver(token_provider=lambda: 'tok_abc')
        completed = Mock(
            returncode=0,
            stdout=json.dumps({'ip': '198.51.100.1'}),
            stderr='',
        )

        with patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ) as run:
            resolver.get(force=True)

        command = run.call_args[0][0]
        self.assertEqual(command[command.index('--token') + 1], 'tok_abc')
        self.assertEqual(run.call_args[1]['env']['IPINFO_TOKEN'], 'tok_abc')

    def test_omits_token_flag_when_unset(self):
        resolver = EgressIpResolver(token_provider=lambda: '')
        completed = Mock(
            returncode=0,
            stdout=json.dumps({'ip': '198.51.100.1'}),
            stderr='',
        )

        with patch.dict('os.environ', {'IPINFO_TOKEN': ''}, clear=False), patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ) as run:
            resolver.get(force=True)

        command = run.call_args[0][0]
        self.assertNotIn('--token', command)
        self.assertFalse(run.call_args[1]['env'].get('IPINFO_TOKEN'))

    def test_rate_limit_returns_dedicated_error(self):
        resolver = EgressIpResolver()
        completed = Mock(
            returncode=1,
            stdout='',
            stderr="err: GET https://ipinfo.io/: 429 You've hit the daily limit",
        )

        with patch(
            'core.egress_ip.subprocess.run',
            return_value=completed,
        ):
            info = resolver.get(force=True)

        self.assertFalse(info['ok'])
        self.assertEqual(info['error'], 'ipinfo_rate_limited')


if __name__ == '__main__':
    unittest.main()
