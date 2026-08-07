import unittest
from unittest.mock import call, patch

from core.v2ray_controller import V2rayController


class TproxyServiceTest(unittest.TestCase):
    def test_first_successful_node_application_configures_and_enables_service(self):
        controller = V2rayController()
        with patch.object(
            controller,
            '_iptables_service_state',
            return_value=False,
        ) as service_state, patch(
            'core.v2ray_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        service_state.assert_called_once_with('is-enabled')
        self.assertEqual(check_output.call_args_list, [
            call('bash ./script/config_iptable.sh', shell=True),
            call('systemctl enable xray_iptable.service', shell=True),
        ])

    def test_enabled_but_inactive_service_is_started(self):
        controller = V2rayController()
        with patch.object(
            controller,
            '_iptables_service_state',
            side_effect=[True, False],
        ) as service_state, patch(
            'core.v2ray_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        self.assertEqual(service_state.call_args_list, [
            call('is-enabled'),
            call('is-active'),
        ])
        check_output.assert_called_once_with(
            'systemctl start xray_iptable.service', shell=True,
        )

    def test_enabled_and_active_service_is_left_unchanged(self):
        controller = V2rayController()
        with patch.object(
            controller,
            '_iptables_service_state',
            side_effect=[True, True],
        ) as service_state, patch(
            'core.v2ray_controller.subprocess.check_output',
        ) as check_output:
            self.assertTrue(controller.enable_iptables())

        self.assertEqual(service_state.call_args_list, [
            call('is-enabled'),
            call('is-active'),
        ])
        check_output.assert_not_called()


if __name__ == '__main__':
    unittest.main()

class CoreServiceTproxyIntegrationTest(unittest.TestCase):
    def test_every_successful_node_reapply_ensures_tproxy_service(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from core.core_service import CoreService

        user_config = SimpleNamespace(node=SimpleNamespace(add='node.example.com'))
        node_manager = Mock()
        v2ray = Mock()
        v2ray.apply_node.return_value = True

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
            v2ray=v2ray,
        ):
            self.assertTrue(CoreService.re_apply_node(restart_auto_detect=False))

        v2ray.enable_iptables.assert_called_once_with()

    def test_failed_node_reapply_does_not_enable_tproxy_service(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from core.core_service import CoreService

        user_config = SimpleNamespace(node=SimpleNamespace(add='node.example.com'))
        node_manager = Mock()
        v2ray = Mock()
        v2ray.apply_node.return_value = False

        with patch.multiple(
            CoreService,
            user_config=user_config,
            node_manager=node_manager,
            v2ray=v2ray,
        ):
            self.assertFalse(CoreService.re_apply_node(restart_auto_detect=False))

        v2ray.enable_iptables.assert_not_called()
