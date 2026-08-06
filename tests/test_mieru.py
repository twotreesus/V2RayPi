import json
import signal
import subprocess
import tempfile
import unittest

from core.mieru_controller import MieruController
from core.node import Node
from core.node_manager import NodeManager
from core.v2ray_config import V2RayConfig
from core.v2ray_user_config import V2RayUserConfig


class MieruNodeTest(unittest.TestCase):
    def test_parse_simple_link_with_port_bindings(self):
        url = (
            'mierus://user:pass@example.com?'
            'port=6666&port=9998-9999&port=6489&'
            'protocol=TCP&protocol=TCP&protocol=UDP&'
            'mtu=1400&multiplexing=MULTIPLEXING_HIGH&'
            'handshake-mode=HANDSHAKE_NO_WAIT#demo'
        )
        node = Node().load_data(Node.mieru_uri_to_data(url))

        self.assertEqual(node.protocol, 'mieru')
        self.assertEqual(node.username, 'user')
        self.assertEqual(node.password, 'pass')
        self.assertEqual(node.port_bindings[1]['portRange'], '9998-9999')
        self.assertEqual(node.port_bindings[2]['protocol'], 'UDP')
        self.assertEqual(node.handshake_mode, 'HANDSHAKE_NO_WAIT')

    def test_parse_clash_mieru_hostname_node(self):
        proxy = {
            'name': '新加坡 D - 高级节点 | 国际专线 | ChatGPT解锁',
            'type': 'mieru',
            'server': 'sgzone.wpscdn.pp.ua',
            'transport': 'TCP',
            'username': 'u15536',
            'password': 'eXkNaq',
            'udp': True,
            'port': 15407,
        }
        node = NodeManager()._clash_proxy_to_node(proxy)

        self.assertEqual(node.protocol, 'mieru')
        self.assertEqual(node.ps, proxy['name'])
        self.assertEqual(node.add, 'sgzone.wpscdn.pp.ua')
        self.assertEqual(node.port, 15407)
        self.assertEqual(node.username, 'u15536')
        self.assertEqual(node.password, 'eXkNaq')
        self.assertTrue(node.udp)
        self.assertEqual(node.port_bindings, [{'port': 15407, 'protocol': 'TCP'}])

        server = MieruController()._gen_config(node)['profiles'][0]['servers'][0]
        self.assertEqual(server['domainName'], 'sgzone.wpscdn.pp.ua')
        self.assertNotIn('ipAddress', server)
        self.assertEqual(server['portBindings'], [{'port': 15407, 'protocol': 'TCP'}])

    def test_generate_native_client_config(self):
        node = Node().load_data({
            'protocol': 'mieru',
            'add': '1.2.3.4',
            'port': 6666,
            'username': 'user',
            'password': 'pass',
            'port_bindings': [
                {'port': 6666, 'protocol': 'TCP'},
                {'portRange': '9998-9999', 'protocol': 'UDP'},
            ],
            'mtu': 1400,
            'multiplexing': 'MULTIPLEXING_HIGH',
            'handshake_mode': 'HANDSHAKE_STANDARD',
        })
        config = MieruController()._gen_config(node)
        profile = config['profiles'][0]

        self.assertEqual(config['socks5Port'], 2335)
        self.assertEqual(profile['user'], {'name': 'user', 'password': 'pass'})
        self.assertEqual(profile['servers'][0]['portBindings'][1]['portRange'], '9998-9999')
        self.assertEqual(profile['multiplexing'], {'level': 'MULTIPLEXING_HIGH'})

    def test_xray_uses_mieru_sidecar_socks(self):
        user_config = V2RayUserConfig().load()
        node = Node().load_data({
            'protocol': 'mieru',
            'add': '1.2.3.4',
            'port': 6666,
            'username': 'user',
            'password': 'pass',
        })
        user_config.node = node
        config = json.loads(V2RayConfig.gen_config(user_config, [node], [], 2335))
        proxy = next(item for item in config['outbounds'] if item.get('tag') == 'proxy')

        self.assertEqual(proxy['protocol'], 'socks')
        self.assertEqual(proxy['settings']['servers'][0], {
            'address': '127.0.0.1',
            'port': 2335,
        })

    def test_linux_tproxy_dns_uses_mieru_socks_sidecar(self):
        # The original UDP/53 packet is consumed by dns-out.  DNS server
        # traffic to the remote resolver is then routed to proxy, which is the
        # Mieru local SOCKS5 listener.  This avoids routing the intercepted
        # request itself to SOCKS and preserves Xray's DNS domain rules.
        from unittest.mock import patch

        user_config = V2RayUserConfig().load()
        user_config.proxy_mode = V2RayUserConfig.ProxyMode.ProxyGlobal.value
        node = Node().load_data({
            'protocol': 'mieru',
            'add': '1.2.3.4',
            'port': 6666,
            'username': 'user',
            'password': 'pass',
            'udp': True,
        })
        user_config.node = node

        with patch('core.v2ray_config.sys.platform', 'linux'):
            config = json.loads(V2RayConfig.gen_config(user_config, [node], [], 2335))

        transparent = next(item for item in config['inbounds'] if item.get('tag') == 'transparent')
        self.assertEqual(transparent['protocol'], 'dokodemo-door')
        self.assertEqual(transparent['port'], 12345)
        self.assertEqual(transparent['streamSettings']['sockopt']['tproxy'], 'tproxy')

        dns_out_rule = next(
            item for item in config['routing']['rules']
            if item.get('inboundTag') == ['transparent']
            and item.get('network') == 'udp'
            and item.get('port') == 53
        )
        self.assertEqual(dns_out_rule['outboundTag'], 'dns-out')

        remote_dns = user_config.advance_config.dns.remote_dns()
        remote_dns_rule = next(
            item for item in config['routing']['rules']
            if item.get('ip') == [remote_dns]
        )
        self.assertEqual(remote_dns_rule['outboundTag'], 'proxy')

        proxy = next(item for item in config['outbounds'] if item.get('tag') == 'proxy')
        self.assertEqual(proxy['protocol'], 'socks')
        self.assertEqual(proxy['settings']['servers'][0], {
            'address': '127.0.0.1',
            'port': 2335,
        })


class MieruProcessTest(unittest.TestCase):
    def test_apply_node_restarts_running_daemon_for_profile_switch(self):
        from unittest.mock import Mock, patch

        apply_result = Mock(returncode=0, stdout='')
        start_result = Mock(returncode=0, stdout='')
        node = Node().load_data({
            'protocol': 'mieru',
            'add': 'second.example.com',
            'port': 15407,
            'username': 'user2',
            'password': 'pass2',
        })

        with tempfile.TemporaryDirectory() as temp_dir:
            controller = MieruController(
                binary='/usr/local/bin/mieru',
                config_path=temp_dir + '/client.json',
            )
            with patch.object(
                controller,
                '_run',
                side_effect=[apply_result, start_result],
            ) as run, patch.object(
                controller,
                'running',
                side_effect=[True, False, True],
            ):
                self.assertTrue(controller.apply_node(node))

        self.assertEqual(run.call_args_list[0].args[:3], ('apply', 'config', controller.config_path))
        self.assertEqual(run.call_args_list[1].args, ('start',))

    def test_stop_kills_running_daemon_without_rpc(self):
        from unittest.mock import call, patch

        controller = MieruController(binary='/usr/local/bin/mieru')
        with patch.object(controller, '_pids', return_value=[1234]), patch.object(
            controller,
            '_wait_for_running',
            return_value=True,
        ), patch.object(controller, '_signal_pids') as signal_pids, patch.object(
            controller,
            '_run',
        ) as run:
            self.assertTrue(controller.stop())

        run.assert_not_called()
        self.assertEqual(signal_pids.call_args_list, [call([1234], signal.SIGKILL)])

    def test_start_does_not_wait_for_daemon_stdio_pipe(self):
        from unittest.mock import Mock, patch

        result = Mock(returncode=0, stdout='')
        controller = MieruController(binary='/usr/local/bin/mieru')
        with patch('core.mieru_controller.subprocess.run', return_value=result) as run:
            self.assertIs(run.return_value, controller._run('start', check=True))

        self.assertEqual(run.call_args.args[0], ['/usr/local/bin/mieru', 'start'])
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertTrue(run.call_args.kwargs['start_new_session'])
        self.assertTrue(run.call_args.kwargs['check'])


class MieruUpdateTest(unittest.TestCase):
    def test_check_new_version(self):
        from unittest.mock import Mock, patch

        response = Mock()
        response.json.return_value = {'tag_name': 'v3.35.0'}
        with patch('core.mieru_controller.requests.get', return_value=response) as get:
            self.assertEqual(MieruController().check_new_version(), 'v3.35.0')
        get.assert_called_once_with(
            'https://api.github.com/repos/enfein/mieru/releases/latest',
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()

    def test_update_returns_script_status(self):
        from unittest.mock import Mock, patch

        success = Mock(returncode=0, stdout='installed')
        with patch('core.mieru_controller.subprocess.run', return_value=success) as run:
            self.assertTrue(MieruController().update())
        command = run.call_args.args[0]
        self.assertEqual(command[-1], 'update')
        self.assertEqual(command[-2].split('/')[-1], 'update_mieru.sh')

        failure = Mock(returncode=1, stdout='download failed')
        with patch('core.mieru_controller.subprocess.run', return_value=failure):
            self.assertFalse(MieruController().update())


if __name__ == '__main__':
    unittest.main()
