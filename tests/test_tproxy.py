import os
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import requests

from core.mihomo_controller import MihomoController
from core.mihomo_default_path import MihomoDefaultPath


class DefaultPathTest(unittest.TestCase):
    def test_apple_silicon_uses_homebrew_service_log(self):
        with patch('core.mihomo_default_path.sys.platform', 'darwin'), patch(
            'core.mihomo_default_path.platform.machine', return_value='arm64',
        ):
            self.assertEqual(
                MihomoDefaultPath.log_file(),
                '/opt/homebrew/var/log/mihomo.log',
            )

    def test_intel_macos_uses_homebrew_service_log(self):
        with patch('core.mihomo_default_path.sys.platform', 'darwin'), patch(
            'core.mihomo_default_path.platform.machine', return_value='x86_64',
        ):
            self.assertEqual(
                MihomoDefaultPath.log_file(),
                '/usr/local/var/log/mihomo.log',
            )


class MihomoVersionTest(unittest.TestCase):
    def test_homebrew_version_without_v_prefix_is_normalized(self):
        completed = Mock(
            returncode=0,
            stdout='Mihomo Meta 1.19.29 darwin arm64 with go1.26.5',
        )
        with patch(
            'core.mihomo_controller.subprocess.run',
            return_value=completed,
        ):
            self.assertEqual(MihomoController().version(), 'v1.19.29')

    def test_official_version_with_v_prefix_is_preserved(self):
        completed = Mock(
            returncode=0,
            stdout='Mihomo Meta v1.19.29 linux arm64 with go1.24',
        )
        with patch(
            'core.mihomo_controller.subprocess.run',
            return_value=completed,
        ):
            self.assertEqual(MihomoController().version(), 'v1.19.29')


class MihomoStartedAtTest(unittest.TestCase):
    def test_returns_create_time_of_the_mihomo_process(self):
        completed = Mock(returncode=0, stdout='1234\n')
        proc = Mock()
        proc.create_time.return_value = 1700000000.5
        with patch(
            'core.mihomo_controller.subprocess.run',
            return_value=completed,
        ), patch(
            'core.mihomo_controller.psutil.Process',
            return_value=proc,
        ) as process:
            self.assertEqual(MihomoController().started_at(), 1700000000.5)
        process.assert_called_once_with(1234)

    def test_returns_none_when_mihomo_is_not_running(self):
        completed = Mock(returncode=1, stdout='')
        with patch(
            'core.mihomo_controller.subprocess.run',
            return_value=completed,
        ):
            self.assertIsNone(MihomoController().started_at())


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

    def test_geo_initialization_persists_the_downloaded_release_version(self):
        from core.core_service import CoreService
        from core.mihomo_user_config import MihomoUserConfig

        user_config = MihomoUserConfig()
        mihomo = Mock()
        mihomo.check_new_geo_data.return_value = '202608080001'

        with patch.object(user_config, 'save') as save, patch.multiple(
            CoreService,
            user_config=user_config,
            mihomo=mihomo,
        ):
            CoreService.update_geo_data()

        mihomo.update_geo_data.assert_called_once_with(
            user_config.advance_config.geo_data.check_url,
        )
        self.assertEqual(
            user_config.advance_config.geo_data.current_version,
            '202608080001',
        )
        save.assert_called_once_with()


class ApplyConfigTest(unittest.TestCase):
    def test_invalid_config_is_never_written(self):
        controller = MihomoController()
        with patch.object(controller, 'test_config', return_value=False), patch(
            'builtins.open',
        ) as open_mock, patch.object(controller, 'restart') as restart_mock:
            self.assertFalse(controller.apply_config('mode: nonsense'))

        open_mock.assert_not_called()
        restart_mock.assert_not_called()

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

    def test_valid_config_restarts_mihomo(self):
        controller = MihomoController()
        with patch.object(controller, 'test_config', return_value=True), patch(
            'core.mihomo_controller.os.makedirs',
        ), patch('builtins.open'), patch.object(
            controller, 'restart', return_value=True,
        ) as restart:
            self.assertTrue(controller.apply_config('mode: rule'))

        restart.assert_called_once_with()

    def test_reloading_through_the_api_skips_mihomo_test(self):
        controller = MihomoController()
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'config.yaml')
            with open(config_file, 'w') as f:
                f.write('mode: rule\n')
            with patch.object(controller, 'running', return_value=True), patch(
                'core.mihomo_controller.MihomoDefaultPath.config_file',
                return_value=config_file,
            ), patch.object(controller, 'test_config') as test_config, patch.object(
                controller, 'reload_config', return_value=True,
            ) as reload_config, patch.object(controller, 'restart') as restart:
                self.assertTrue(controller.apply_config('mode: global', 'deadbeef'))

            test_config.assert_not_called()
            reload_config.assert_called_once_with('deadbeef')
            restart.assert_not_called()
            with open(config_file) as f:
                self.assertEqual(f.read(), 'mode: global')

    def test_a_core_without_a_reachable_api_falls_back_to_a_restart(self):
        controller = MihomoController()
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'config.yaml')
            with open(config_file, 'w') as f:
                f.write('mode: rule\n')
            with patch.object(controller, 'running', return_value=True), patch(
                'core.mihomo_controller.MihomoDefaultPath.config_file',
                return_value=config_file,
            ), patch.object(controller, 'test_config', return_value=True) as test_config, patch.object(
                controller, 'reload_config', return_value=False,
            ), patch.object(controller, 'restart', return_value=True) as restart:
                self.assertTrue(controller.apply_config('mode: global', 'deadbeef'))

            test_config.assert_called_once_with('mode: global')
            restart.assert_called_once_with()
            with open(config_file) as f:
                self.assertEqual(f.read(), 'mode: global')

    def test_rejected_api_reload_restores_the_previous_config(self):
        controller = MihomoController()
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'config.yaml')
            with open(config_file, 'w') as f:
                f.write('mode: rule\n')
            with patch.object(controller, 'running', return_value=True), patch(
                'core.mihomo_controller.MihomoDefaultPath.config_file',
                return_value=config_file,
            ), patch.object(controller, 'test_config', return_value=False), patch.object(
                controller, 'reload_config', return_value=False,
            ), patch.object(controller, 'restart') as restart:
                self.assertFalse(controller.apply_config('mode: nonsense', 'deadbeef'))

            restart.assert_not_called()
            with open(config_file) as f:
                self.assertEqual(f.read(), 'mode: rule\n')


class ControlApiTest(unittest.TestCase):
    def test_the_running_secret_is_carried_over_into_the_new_config(self):
        # A freshly minted secret would not match the one the running core
        # authenticates with, costing a restart on every node application.
        controller = MihomoController()
        with patch.object(controller, 'api_secret', return_value='live-secret'), patch(
            'core.mihomo_controller.MihomoConfig.gen_config', return_value='mode: rule',
        ) as gen_config, patch.object(
            controller, 'apply_config', return_value=True,
        ) as apply_config:
            self.assertTrue(controller.apply_node(Mock(), []))

        self.assertEqual(gen_config.call_args.kwargs['controller_secret'], 'live-secret')
        apply_config.assert_called_once_with('mode: rule', 'live-secret')

    def test_secret_is_read_from_the_live_config(self):
        controller = MihomoController()
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'config.yaml')
            with open(config_file, 'w') as f:
                f.write('mode: rule\nsecret: live-secret\n')
            with patch(
                'core.mihomo_controller.MihomoDefaultPath.config_file',
                return_value=config_file,
            ):
                self.assertEqual(controller.api_secret(), 'live-secret')

    def test_a_config_without_a_secret_yields_an_empty_one(self):
        controller = MihomoController()
        with tempfile.TemporaryDirectory() as config_dir:
            config_file = os.path.join(config_dir, 'config.yaml')
            with open(config_file, 'w') as f:
                f.write('mode: direct\n')
            with patch(
                'core.mihomo_controller.MihomoDefaultPath.config_file',
                return_value=config_file,
            ):
                self.assertEqual(controller.api_secret(), '')

    def test_reload_is_authenticated_and_forced(self):
        controller = MihomoController()
        with patch.object(controller, 'running', return_value=True), patch(
            'core.mihomo_controller.requests.put',
            return_value=Mock(status_code=204, text=''),
        ) as put, patch(
            'core.mihomo_controller.MihomoDefaultPath.config_file',
            return_value='/etc/mihomo/config.yaml',
        ):
            self.assertTrue(controller.reload_config('live-secret'))

        url = put.call_args[0][0]
        self.assertIn('force=true', url)
        self.assertEqual(
            put.call_args.kwargs['headers']['Authorization'],
            'Bearer live-secret',
        )
        self.assertEqual(
            put.call_args.kwargs['json'],
            {'path': '/etc/mihomo/config.yaml'},
        )

    def test_reload_of_a_stopped_core_does_not_reach_the_api(self):
        controller = MihomoController()
        with patch.object(controller, 'running', return_value=False), patch(
            'core.mihomo_controller.requests.put',
        ) as put:
            self.assertFalse(controller.reload_config('live-secret'))

        put.assert_not_called()

    def test_an_unreachable_api_is_reported_as_a_failed_reload(self):
        controller = MihomoController()
        with patch.object(controller, 'running', return_value=True), patch(
            'core.mihomo_controller.requests.put',
            side_effect=requests.ConnectionError('connection refused'),
        ):
            self.assertFalse(controller.reload_config('live-secret'))


class GeoDataUpdateTest(unittest.TestCase):
    def test_downloads_both_databases_before_replacing_existing_files(self):
        controller = MihomoController()
        geoip_response = Mock(headers={'content-length': '9'})
        geoip_response.iter_content.return_value = [b'new-geoip']
        geosite_response = Mock(headers={'content-length': '11'})
        geosite_response.iter_content.return_value = [b'new-geosite']

        with tempfile.TemporaryDirectory() as asset_path, patch(
            'core.mihomo_controller.MihomoDefaultPath.asset_path',
            return_value=asset_path + '/',
        ), patch(
            'core.mihomo_controller.requests.get',
            side_effect=[geoip_response, geosite_response],
        ), patch.object(
            controller, 'running', return_value=True,
        ), patch.object(
            controller, 'service_available', return_value=True,
        ), patch.object(controller, 'restart', return_value=True) as restart:
            controller.update_geo_data('https://example.com/releases')

            with open(os.path.join(asset_path, 'geoip.dat'), 'rb') as f:
                self.assertEqual(f.read(), b'new-geoip')
            with open(os.path.join(asset_path, 'geosite.dat'), 'rb') as f:
                self.assertEqual(f.read(), b'new-geosite')

        geoip_response.raise_for_status.assert_called_once_with()
        geosite_response.raise_for_status.assert_called_once_with()
        restart.assert_called_once_with()

    def test_skips_restart_when_mihomo_is_not_running(self):
        controller = MihomoController()
        geoip_response = Mock(headers={'content-length': '9'})
        geoip_response.iter_content.return_value = [b'new-geoip']
        geosite_response = Mock(headers={'content-length': '11'})
        geosite_response.iter_content.return_value = [b'new-geosite']

        with tempfile.TemporaryDirectory() as asset_path, patch(
            'core.mihomo_controller.MihomoDefaultPath.asset_path',
            return_value=asset_path + '/',
        ), patch(
            'core.mihomo_controller.requests.get',
            side_effect=[geoip_response, geosite_response],
        ), patch.object(
            controller, 'running', return_value=False,
        ), patch.object(
            controller, 'service_available', return_value=False,
        ), patch.object(controller, 'restart') as restart:
            controller.update_geo_data('https://example.com/releases')

        restart.assert_not_called()

    def test_skips_restart_when_service_unit_is_missing(self):
        controller = MihomoController()
        geoip_response = Mock(headers={'content-length': '9'})
        geoip_response.iter_content.return_value = [b'new-geoip']
        geosite_response = Mock(headers={'content-length': '11'})
        geosite_response.iter_content.return_value = [b'new-geosite']

        with tempfile.TemporaryDirectory() as asset_path, patch(
            'core.mihomo_controller.MihomoDefaultPath.asset_path',
            return_value=asset_path + '/',
        ), patch(
            'core.mihomo_controller.requests.get',
            side_effect=[geoip_response, geosite_response],
        ), patch.object(
            controller, 'running', return_value=True,
        ), patch.object(
            controller, 'service_available', return_value=False,
        ), patch.object(controller, 'restart') as restart:
            controller.update_geo_data('https://example.com/releases')

        restart.assert_not_called()

    def test_failed_download_keeps_existing_databases_unchanged(self):
        controller = MihomoController()
        geoip_response = Mock(headers={'content-length': '9'})
        geoip_response.iter_content.return_value = [b'new-geoip']
        geosite_response = Mock()
        geosite_response.raise_for_status.side_effect = RuntimeError('download failed')

        with tempfile.TemporaryDirectory() as asset_path:
            for filename, content in (
                ('geoip.dat', b'old-geoip'),
                ('geosite.dat', b'old-geosite'),
            ):
                with open(os.path.join(asset_path, filename), 'wb') as f:
                    f.write(content)

            with patch(
                'core.mihomo_controller.MihomoDefaultPath.asset_path',
                return_value=asset_path + '/',
            ), patch(
                'core.mihomo_controller.requests.get',
                side_effect=[geoip_response, geosite_response],
            ), patch.object(
                controller, 'running', return_value=False,
            ), patch.object(controller, 'restart') as restart:
                with self.assertRaisesRegex(RuntimeError, 'download failed'):
                    controller.update_geo_data('https://example.com/releases')

            with open(os.path.join(asset_path, 'geoip.dat'), 'rb') as f:
                self.assertEqual(f.read(), b'old-geoip')
            with open(os.path.join(asset_path, 'geosite.dat'), 'rb') as f:
                self.assertEqual(f.read(), b'old-geosite')
            restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
