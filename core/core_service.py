# encoding: utf-8
"""
File:       core_service
Author:     twotrees.us@gmail.com
Date:       2020年7月30日  31周星期四 10:55
Desc:
"""
import psutil
import os
import os.path
from .package import jsonpickle
from typing import List
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import *
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import random
import time

from .app_config import AppConfig
from .v2ray_controller import V2rayController, make_controller
from .node_manager import NodeManager
from .keys import Keyword as K
from .v2ray_user_config import V2RayUserConfig

class CoreService:
    app_config : AppConfig = None
    user_config: V2RayUserConfig = V2RayUserConfig()
    v2ray:V2rayController = make_controller()
    node_manager:NodeManager = NodeManager()
    scheduler:BackgroundScheduler = BackgroundScheduler(
        {
            'apscheduler.executors.default': {
                'class': 'apscheduler.executors.pool:ThreadPoolExecutor',
                'max_workers': '1'
            }
        })

    @classmethod
    def load(cls):
        config_path = 'config/'
        if not os.path.exists(config_path):
            os.mkdir(config_path)

        cls.app_config = AppConfig().load()
        cls.node_manager = NodeManager().load()
        cls.user_config = V2RayUserConfig().load()

        cls.restart_auto_detect()

    @classmethod
    def status(cls) -> dict:
        running = cls.v2ray.running()
        version = cls.v2ray.version()

        result = {
            K.running: running,
            K.version: version,
            K.proxy_mode: cls.user_config.proxy_mode,
        }

        node = cls.user_config.node.dump()
        result.update(node)
        return result

    @classmethod
    def performance(cls) -> dict:
        result = {}
        cpu_usage = psutil.cpu_percent(interval=0.2, percpu=True)
        result_cpu = {}
        core = 0
        for u in cpu_usage:
            core += 1
            result_cpu["core {0}".format(core)] = u
        result['cpu'] = result_cpu

        memory_usage = psutil.virtual_memory()
        result['memory'] = {
            "percent" : memory_usage.percent,
            "total" : int(memory_usage.total / (1024 * 1024)),
            "used" : int((memory_usage.total - memory_usage.available) / (1024 * 1024))
        }
        return result

    @classmethod
    def add_subscribe(cls, url):
        cls.node_manager.add_subscribe(url)
        cls.re_apply_node()

    @classmethod
    def remove_subscribe(cls, url):
        cls.node_manager.remove_subscribe(url)
        cls.re_apply_node()

    @classmethod
    def update_all_subscribe(cls):
        cls.node_manager.update_all()
        cls.re_apply_node()

    @classmethod
    def update_subscribe(cls, url):
        cls.node_manager.update(url)
        cls.re_apply_node()

    @classmethod
    def add_manual_node(cls, url):
        cls.node_manager.add_manual_node(url)
        cls.re_apply_node()

    @classmethod
    def delete_node(cls, url, index):
        cls.node_manager.delete_node(url, index)
        cls.re_apply_node()

    @classmethod
    def re_apply_node(cls, restart_auto_detect=True) -> bool:
        if not cls.user_config.node.add:
            return True

        result = cls.v2ray.apply_node(cls.user_config, cls.node_manager.all_nodes())
        if restart_auto_detect:
            cls.restart_auto_detect()
        return result

    @classmethod
    def restart_auto_detect(cls):
        cls.auto_detect_cancel()
        if cls.user_config.advance_config.auto_detect.enabled :
            cls.auto_detect_start()

    @classmethod
    def stop_v2ray(cls) -> bool:
        result = cls.v2ray.stop()
        cls.auto_detect_cancel()

        return result

    @classmethod
    def apply_node(cls, url:str, index: int, restart_auto_detect=True) -> bool:
        result = False
        node = cls.node_manager.find_node(url, index)
        cls.user_config.node = node
        if cls.re_apply_node(restart_auto_detect):
            cls.user_config.save()

            if not cls.app_config.inited:
                cls.v2ray.enable_iptables()
                cls.app_config.inited = True
                cls.app_config.save()
            result = True
        return result

    @classmethod
    def switch_mode(cls, proxy_mode: int) -> bool:
        cls.user_config.proxy_mode = proxy_mode
        result = True
        result = cls.re_apply_node()
        if result:
            cls.user_config.save()

        return result

    @classmethod
    def update_v2ray(cls) -> bool:
        result = True
        result = cls.v2ray.update()
        if result:
            if cls.user_config.advance_config.geo_data.current_version != '':
                cls.update_geo_data()

        return result

    @classmethod
    def check_new_geo_data(cls) -> str:
        check_url = cls.user_config.advance_config.geo_data.check_url
        new_version = cls.v2ray.check_new_geo_data(check_url)
        return new_version

    @classmethod
    def update_geo_data(cls):
        check_url = cls.user_config.advance_config.geo_data.check_url
        new_version = cls.v2ray.check_new_geo_data(check_url)

        cls.v2ray.update_geo_data(check_url)
        cls.user_config.advance_config.geo_data.current_version = new_version
        cls.user_config.save()

    @classmethod
    def apply_advance_config(cls, config:dict):
        result = True
        new_advance = cls.user_config.advance_config.load_data(config)
        cls.user_config.advance_config = new_advance
        result = cls.re_apply_node()
        if result:
            cls.user_config.save()
        return  result

    @classmethod
    def reset_advance_config(cls):
        result = True
        cls.user_config.advance_config = V2RayUserConfig.AdvanceConfig()
        result = cls.re_apply_node()
        if result:
            cls.user_config.save()
        return result

    @classmethod
    def make_policy(cls, contents:List[str], type:str, outbound:str) -> dict:
        type = V2RayUserConfig.AdvanceConfig.Policy.Type[type]
        outbound = V2RayUserConfig.AdvanceConfig.Policy.Outbound[outbound]
        policy = V2RayUserConfig.AdvanceConfig.Policy()
        policy.contents = contents
        policy.type = type.name
        policy.outbound = outbound.name
        return jsonpickle.encode(policy, indent=4)

    @classmethod
    def auto_detect_start(cls):
        cls.scheduler.add_job(CoreService.auto_detect_job, trigger='interval', seconds=cls.user_config.advance_config.auto_detect.detect_span, id=K.auto_detect)
        if cls.scheduler.state is not STATE_RUNNING :
            cls.scheduler.start()

    @classmethod
    def auto_detect_cancel(cls):
        job = cls.scheduler.get_job(K.auto_detect)
        if job:
            job.remove()

    @classmethod
    def auto_detect_job(cls):
        detect:V2RayUserConfig.AdvanceConfig.AutoDetectAndSwitch = cls.user_config.advance_config.auto_detect

        DEFAULT_TIMEOUT = 5 # seconds
        class TimeoutHTTPAdapter(HTTPAdapter):
            def __init__(self, *args, **kwargs):
                self.timeout = DEFAULT_TIMEOUT
                if "timeout" in kwargs:
                    self.timeout = kwargs["timeout"]
                    del kwargs["timeout"]
                super().__init__(*args, **kwargs)

            def send(self, request, **kwargs):
                timeout = kwargs.get("timeout")
                if timeout is None:
                    kwargs["timeout"] = self.timeout
                return super().send(request, **kwargs)

        # begin detect
        retries = Retry(total=detect.failed_count, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        http = requests.Session()
        http.mount("https://", TimeoutHTTPAdapter(max_retries=retries, timeout=detect.timeout))

        try:
            http.get(detect.detect_url)
            print('detected connetion success, nothing to do, just return')
            return
        except Exception as e:
            print('detected connetion failed, detail:\n{0}'.format(e))

        # failed prepare to switch node
        ping_groups = cls.node_manager.ping_test_all()
        class NodePingInfo:
            def __init__(self, group_key:str, node_ps:str, ping:int):
                self.group_key:str = group_key
                self.node_ps:str = node_ps
                self.ping:int = ping

            def __lt__(self, other):
                return self.ping < other.ping

        ping_results = []
        for group in ping_groups:
            group_key = group[K.subscribe]
            nodes = group[K.nodes]
            for node_ps in nodes.keys():
                ping = nodes[node_ps]
                info = NodePingInfo(group_key, node_ps, ping)
                ping_results.append(info)

        ping_results.sort()
        best_nodes = ping_results[:5]
        random.shuffle(best_nodes)
        best_node = best_nodes[0]

        node_index = cls.node_manager.find_node_index(best_node.group_key, best_node.node_ps)
        cls.apply_node(best_node.group_key, node_index, restart_auto_detect=False)

        detect.last_switch_time = '{0} ---- {1}'.format(datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S'), best_node.node_ps)
        cls.user_config.save()