import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.core_service import CoreService


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

        with patch(
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


class AutoSwitchTest(unittest.TestCase):
    def test_failed_probe_switches_to_another_node_without_latency_test(self):
        current = SimpleNamespace(
            protocol='vmess', add='current.example.com', port=443, ps='current',
        )
        alternative = SimpleNamespace(
            protocol='vless', add='next.example.com', port=8443, ps='next',
        )
        detect = SimpleNamespace(
            failed_count=1,
            timeout=0.5,
            detect_url='https://example.com/',
            last_switch_time='',
        )
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
        session.get.side_effect = RuntimeError('probe failed')

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
        ), patch(
            'core.core_service.requests.Session',
            return_value=session,
        ), patch(
            'core.core_service.random.choice',
            return_value=('subscription', 1, alternative),
        ), patch.object(
            CoreService,
            'apply_node',
            return_value=True,
        ) as apply_node:
            CoreService.auto_detect_job()

        apply_node.assert_called_once_with(
            'subscription',
            1,
            restart_auto_detect=False,
        )
        self.assertIn('next', detect.last_switch_time)
        user_config.save.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
