import unittest
from unittest.mock import Mock, call, patch

from core.mihomo_controller import MihomoController


class TproxyServiceTest(unittest.TestCase):
    def test_first_successful_node_application_configures_and_enables_service(self):
        controller = MihomoController()
        with patch.object(
            controller,
            '_iptables_service_state',
            return_value=False,
        ) as service_state, patch(
            'core.mihomo_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        service_state.assert_called_once_with('is-enabled')
        self.assertEqual(check_output.call_args_list, [
            call('bash ./script/config_iptable.sh', shell=True),
            call('systemctl enable mihomo_iptable.service', shell=True),
        ])

    def test_enabled_but_inactive_service_is_started(self):
        controller = MihomoController()
        with patch.object(
            controller,
            '_iptables_service_state',
            side_effect=[True, False],
        ) as service_state, patch(
            'core.mihomo_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        self.assertEqual(service_state.call_args_list, [
            call('is-enabled'),
            call('is-active'),
        ])
        check_output.assert_called_once_with(
            'systemctl start mihomo_iptable.service', shell=True,
        )

    def test_enabled_and_active_service_is_left_unchanged(self):
        controller = MihomoController()
        with patch.object(
            controller,
            '_iptables_service_state',
            side_effect=[True, True],
        ) as service_state, patch(
            'core.mihomo_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        self.assertEqual(service_state.call_args_list, [
            call('is-enabled'),
            call('is-active'),
        ])
        check_output.assert_not_called()


class CoreServiceTproxyIntegrationTest(unittest.TestCase):
    def test_every_successful_node_reapply_ensures_tproxy_service(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from core.core_service import CoreService

        user_config = SimpleNamespace(node=SimpleNamespace(add='node.example.com'))
        node_manager = Mock()
        mihomo = Mock()
        mihomo.apply_node.return_value = True

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
            mihomo=mihomo,
        ):
            self.assertTrue(CoreService.re_apply_node(restart_auto_detect=False))

        mihomo.enable_iptables.assert_called_once_with()

    def test_failed_node_reapply_does_not_enable_tproxy_service(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from core.core_service import CoreService

        user_config = SimpleNamespace(node=SimpleNamespace(add='node.example.com'))
        node_manager = Mock()
        mihomo = Mock()
        mihomo.apply_node.return_value = False

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
            mihomo=mihomo,
        ):
            self.assertFalse(CoreService.re_apply_node(restart_auto_detect=False))

        mihomo.enable_iptables.assert_not_called()


class ApplyConfigTest(unittest.TestCase):
    def test_invalid_config_is_never_written(self):
        controller = MihomoController()
        with patch.object(controller, 'test_config', return_value=False), patch(
            'builtins.open',
        ) as open_mock, patch.object(controller, 'reload') as reload_mock:
            self.assertFalse(controller.apply_config('mode: nonsense'))

        open_mock.assert_not_called()
        reload_mock.assert_not_called()

    def test_validation_reuses_the_live_config_dir_so_geo_data_is_not_redownloaded(self):
        # mihomo downloads geoip.dat/geosite.dat into the directory given by -d;
        # a throwaway directory would re-fetch ~27MB on every node application.
        controller = MihomoController()
        completed = Mock(returncode=0, stdout='')
        with patch('core.mihomo_controller.os.makedirs'), patch(
            'core.mihomo_controller.subprocess.run', return_value=completed,
        ) as run, patch(
            'core.mihomo_controller.MihomoDefaultPath.config_dir',
            return_value='/etc/mihomo/',
        ):
            self.assertTrue(controller.test_config('mode: rule'))

        argv = run.call_args[0][0]
        self.assertEqual(argv[argv.index('-d') + 1], '/etc/mihomo/')
        # -f must point somewhere else, or the running config would be replaced.
        self.assertNotEqual(argv[argv.index('-f') + 1], '/etc/mihomo/config.yaml')

    def test_a_build_without_the_test_flag_does_not_block_node_application(self):
        controller = MihomoController()
        completed = Mock(returncode=2, stdout='flag provided but not defined: -t')
        with patch('core.mihomo_controller.os.makedirs'), patch(
            'core.mihomo_controller.subprocess.run', return_value=completed,
        ):
            self.assertTrue(controller.test_config('mode: rule'))

    def test_rejected_config_fails_validation(self):
        controller = MihomoController()
        completed = Mock(returncode=1, stdout='rules[3] error: bad rule')
        with patch('core.mihomo_controller.os.makedirs'), patch(
            'core.mihomo_controller.subprocess.run', return_value=completed,
        ):
            self.assertFalse(controller.test_config('mode: rule'))

    def test_reload_failure_falls_back_to_restart(self):
        controller = MihomoController()
        with patch.object(controller, 'test_config', return_value=True), patch(
            'core.mihomo_controller.os.makedirs',
        ), patch('builtins.open'), patch.object(
            controller, 'reload', return_value=False,
        ), patch.object(controller, 'restart', return_value=True) as restart:
            self.assertTrue(controller.apply_config('mode: rule'))

        restart.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
