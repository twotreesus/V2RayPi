import unittest
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

from core.core_service import CoreService
from core.mihomo_user_config import MihomoUserConfig
from core.keys import Keyword as K


class UpdateCheckTest(unittest.TestCase):
    def test_commit_subject_may_contain_pipe_characters(self):
        fetch_result = Mock(returncode=0)
        branch_result = Mock(returncode=0, stdout='main\n')
        local_result = Mock(returncode=0, stdout='100\n')
        log_result = Mock(
            returncode=0,
            stdout='200|2026-08-08|fix: preserve a|b syntax\n',
            stderr='',
        )

        with patch.object(
            CoreService, 'ensure_origin_fetches_all_branches',
        ), patch(
            'core.core_service.subprocess.run',
            side_effect=[
                fetch_result,
                branch_result,
                local_result,
                log_result,
            ],
        ):
            commits = CoreService.check_v2raypi_updates()

        self.assertEqual(
            commits,
            ['2026-08-08|fix: preserve a|b syntax'],
        )


class OriginFetchRefspecTest(unittest.TestCase):
    def test_widens_single_branch_fetch_refspec(self):
        get_result = Mock(
            returncode=0,
            stdout='+refs/heads/master:refs/remotes/origin/master\n',
            stderr='',
        )
        set_result = Mock(returncode=0, stdout='', stderr='')

        with patch(
            'core.core_service.subprocess.run',
            side_effect=[get_result, set_result],
        ) as run:
            CoreService.ensure_origin_fetches_all_branches('/tmp/repo')

        run.assert_has_calls([
            call(
                ['git', 'config', '--get-all', 'remote.origin.fetch'],
                cwd='/tmp/repo',
                stdout=ANY,
                stderr=ANY,
                universal_newlines=True,
            ),
            call(
                [
                    'git', 'config', 'remote.origin.fetch',
                    CoreService.ORIGIN_FETCH_ALL_BRANCHES,
                ],
                cwd='/tmp/repo',
                stdout=ANY,
                stderr=ANY,
                universal_newlines=True,
            ),
        ])

    def test_skips_when_all_branches_refspec_already_present(self):
        get_result = Mock(
            returncode=0,
            stdout=CoreService.ORIGIN_FETCH_ALL_BRANCHES + '\n',
            stderr='',
        )

        with patch(
            'core.core_service.subprocess.run',
            return_value=get_result,
        ) as run:
            CoreService.ensure_origin_fetches_all_branches('/tmp/repo')

        self.assertEqual(run.call_count, 1)


class AutoSwitchTest(unittest.TestCase):
    def _detect(self, url):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.failed_count = 1
        detect.timeout = 0.5
        detect.detect_url = url
        detect.last_switch_time = ''
        return detect

    def test_failed_custom_url_head_fails_over_among_favorites(self):
        current = SimpleNamespace(
            protocol='vmess', add='current.example.com', port=443, ps='current',
        )
        alternative = SimpleNamespace(
            protocol='vless', add='next.example.com', port=8443, ps='next',
            airport='Nexitally',
        )
        detect = self._detect('https://example.com/')
        user_config = SimpleNamespace(
            node=current,
            advance_config=SimpleNamespace(auto_detect=detect),
            save=Mock(),
        )
        node_manager = SimpleNamespace(
            subscribes={
                'subscription': SimpleNamespace(nodes=[current, alternative]),
            },
            manual_nodes=[current, alternative],
        )
        session = Mock()
        session.head.side_effect = RuntimeError('probe failed')

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch(
            'core.core_service.requests.Session',
            return_value=session,
        ), patch(
            'core.core_service.random.choice',
            return_value=(K.manual, 1, alternative),
        ), patch.object(
            CoreService,
            'apply_node',
            return_value=True,
        ) as apply_node:
            CoreService.auto_detect_job()

        session.head.assert_called_once_with('https://example.com/')
        session.get.assert_not_called()
        apply_node.assert_called_once_with(
            K.manual,
            1,
            restart_auto_detect=False,
        )
        self.assertIn('Nexitally', detect.last_switch_time)
        self.assertIn('next', detect.last_switch_time)
        user_config.save.assert_called_once_with()

    def test_manual_apply_clears_the_last_switch_record(self):
        detect = self._detect('https://example.com/')
        detect.last_switch_time = '2026-08-17 16:00:00 ---- Nexitally ---- next'
        node = SimpleNamespace(ps='chosen')
        user_config = SimpleNamespace(
            node=None,
            advance_config=SimpleNamespace(auto_detect=detect),
            save=Mock(),
        )
        node_manager = SimpleNamespace(find_node=Mock(return_value=node))

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch.object(CoreService, 're_apply_node', return_value=True):
            self.assertTrue(CoreService.apply_node('manual', 0))

        self.assertEqual(detect.last_switch_time, '')
        user_config.save.assert_called_once_with()

    def test_auto_apply_does_not_clear_the_last_switch_record(self):
        detect = self._detect('https://example.com/')
        detect.last_switch_time = 'stale'
        node = SimpleNamespace(ps='chosen')
        user_config = SimpleNamespace(
            node=None,
            advance_config=SimpleNamespace(auto_detect=detect),
            save=Mock(),
        )
        node_manager = SimpleNamespace(find_node=Mock(return_value=node))

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch.object(CoreService, 're_apply_node', return_value=True):
            self.assertTrue(CoreService.apply_node('manual', 0, restart_auto_detect=False))

        self.assertEqual(detect.last_switch_time, 'stale')

    def test_failed_probe_does_not_switch_to_subscription_nodes(self):
        current = SimpleNamespace(
            protocol='vmess', add='current.example.com', port=443, ps='current',
        )
        alternative = SimpleNamespace(
            protocol='vless', add='next.example.com', port=8443, ps='next',
        )
        detect = self._detect('https://example.com/')
        user_config = SimpleNamespace(
            node=current,
            advance_config=SimpleNamespace(auto_detect=detect),
            save=Mock(),
        )
        node_manager = SimpleNamespace(
            subscribes={
                'subscription': SimpleNamespace(nodes=[current, alternative]),
            },
            manual_nodes=[],
        )
        session = Mock()
        session.head.side_effect = RuntimeError('probe failed')

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch(
            'core.core_service.requests.Session',
            return_value=session,
        ), patch.object(
            CoreService,
            'apply_node',
            return_value=True,
        ) as apply_node:
            CoreService.auto_detect_job()

        apply_node.assert_not_called()
        user_config.save.assert_not_called()

    def test_default_url_uses_head_and_does_not_switch_on_success(self):
        current = SimpleNamespace(
            protocol='vmess', add='current.example.com', port=443, ps='current',
        )
        detect = self._detect(
            MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch.LATENCY_PROBE_URL,
        )
        user_config = SimpleNamespace(
            node=current,
            advance_config=SimpleNamespace(auto_detect=detect),
            save=Mock(),
        )
        node_manager = SimpleNamespace(manual_nodes=[current])
        session = Mock()
        session.head.return_value = Mock(status_code=204)

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch(
            'core.core_service.requests.Session',
            return_value=session,
        ), patch.object(
            CoreService,
            'apply_node',
            return_value=True,
        ) as apply_node:
            CoreService.auto_detect_job()

        session.head.assert_called_once_with(
            MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch.LATENCY_PROBE_URL,
        )
        session.get.assert_not_called()
        apply_node.assert_not_called()
        user_config.save.assert_not_called()


class EgressLatencyProbeTest(unittest.TestCase):
    def _https_connection(self, connect=None, request=None):
        conn = Mock()
        conn.connect.side_effect = connect
        conn.request.side_effect = request
        conn.getresponse.return_value.read.return_value = b''
        return conn

    def test_times_head_after_the_tls_handshake(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.detect_url = 'https://www.gstatic.com/generate_204'
        detect.timeout = 0.8
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': True,
            'ip': '203.0.113.10',
        }
        order = []
        times = iter([1.0, 1.128])
        conn = self._https_connection(
            connect=lambda: order.append('connect'),
            request=lambda method, path: order.append((method, path)),
        )

        def monotonic():
            order.append('monotonic')
            return next(times)

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
            return_value=conn,
        ) as connection, patch(
            'core.core_service.time.monotonic',
            side_effect=monotonic,
        ):
            info = CoreService.get_egress_ip()

        connection.assert_called_once_with('www.gstatic.com', 443, timeout=0.8)
        self.assertEqual(order, [
            'connect',
            'monotonic',
            ('HEAD', '/generate_204'),
            'monotonic',
        ])
        conn.close.assert_called_once_with()
        self.assertEqual(info['ip'], '203.0.113.10')
        self.assertEqual(info['latency_ms'], 128)

    def test_skips_probe_when_ip_lookup_fails(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': False,
            'ip': '',
            'error': 'ipinfo_missing',
        }

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
        ) as connection:
            info = CoreService.get_egress_ip()

        connection.assert_not_called()
        self.assertIsNone(info['latency_ms'])

    def test_hides_latency_when_handshake_fails(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.detect_url = 'https://example.com/'
        detect.timeout = 0.5
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': True,
            'ip': '203.0.113.10',
        }
        conn = self._https_connection(connect=RuntimeError('handshake failed'))

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
            return_value=conn,
        ):
            info = CoreService.get_egress_ip()

        conn.request.assert_not_called()
        self.assertEqual(info['ip'], '203.0.113.10')
        self.assertIsNone(info['latency_ms'])

    def test_hides_latency_when_head_fails(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.detect_url = 'https://example.com/'
        detect.timeout = 0.5
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': True,
            'ip': '203.0.113.10',
        }
        conn = self._https_connection(request=RuntimeError('probe failed'))

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
            return_value=conn,
        ):
            info = CoreService.get_egress_ip()

        conn.connect.assert_called_once_with()
        self.assertEqual(info['ip'], '203.0.113.10')
        self.assertIsNone(info['latency_ms'])

    def test_reuses_cached_latency_without_probing_again(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.detect_url = 'https://www.gstatic.com/generate_204'
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': True,
            'ip': '203.0.113.10',
            'latency_ms': 128,
        }

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
        ) as connection:
            info = CoreService.get_egress_ip()

        connection.assert_not_called()
        resolver.update_cache.assert_not_called()
        self.assertEqual(info['latency_ms'], 128)

    def test_force_refresh_probes_again(self):
        detect = MihomoUserConfig.AdvanceConfig.AutoDetectAndSwitch()
        detect.detect_url = 'https://www.gstatic.com/generate_204'
        detect.timeout = 0.8
        user_config = SimpleNamespace(
            advance_config=SimpleNamespace(auto_detect=detect),
        )
        resolver = Mock()
        resolver.get.return_value = {
            'ok': True,
            'ip': '203.0.113.10',
        }
        conn = self._https_connection()

        with patch.multiple(
            CoreService,
            user_config=user_config,
            egress_ip_resolver=resolver,
        ), patch(
            'core.core_service.HTTPSConnection',
            return_value=conn,
        ) as connection:
            CoreService.get_egress_ip(force=True)

        connection.assert_called_once_with('www.gstatic.com', 443, timeout=0.8)
        conn.connect.assert_called_once_with()
        conn.request.assert_called_once_with('HEAD', '/generate_204')
        resolver.update_cache.assert_called_once()


class RestartMihomoTest(unittest.TestCase):
    def test_recycles_the_process_without_reapplying_the_node(self):
        mihomo = Mock()
        mihomo.restart.return_value = True

        with patch.multiple(
            CoreService,
            mihomo=mihomo,
        ), patch.object(
            CoreService, 'invalidate_egress_ip',
        ) as invalidate, patch.object(
            CoreService, 'restart_auto_detect',
        ) as restart_detect:
            self.assertTrue(CoreService.restart_mihomo())

        mihomo.restart.assert_called_once_with()
        mihomo.apply_node.assert_not_called()
        invalidate.assert_called_once_with()
        restart_detect.assert_called_once_with()

    def test_failed_restart_leaves_caches_and_probes_alone(self):
        mihomo = Mock()
        mihomo.restart.return_value = False

        with patch.multiple(
            CoreService,
            mihomo=mihomo,
        ), patch.object(
            CoreService, 'invalidate_egress_ip',
        ) as invalidate, patch.object(
            CoreService, 'restart_auto_detect',
        ) as restart_detect:
            self.assertFalse(CoreService.restart_mihomo())

        invalidate.assert_not_called()
        restart_detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
