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


if __name__ == '__main__':
    unittest.main()
