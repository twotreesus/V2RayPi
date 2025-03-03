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
import platform
import subprocess
from .package import jsonpickle
from typing import List, Dict, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import *
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import random
import time
import threading
import hashlib
import base64
import json
from datetime import datetime, timedelta
import secrets

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

    # Class variable to store active sessions
    _sessions = {}
    _session_key = None
    
    @classmethod
    def _get_session_key(cls) -> str:
        """Get or generate session key for signing tokens"""
        if not cls._session_key:
            # Generate a new key on first use
            cls._session_key = secrets.token_hex(32)
        return cls._session_key
    
    @classmethod
    def _clear_all_sessions(cls):
        """Clear all active sessions and generate new session key"""
        cls._sessions.clear()
        cls._session_key = None  # Force new key generation
        
    @classmethod
    def update_password(cls, old_password: str, new_password: str) -> bool:
        """Update admin password and clear all sessions"""
        # Verify old password first
        if not cls.app_config.verify_password(old_password):
            return False
            
        # Update password
        cls.app_config._update_password(new_password)
        
        # Clear all sessions
        cls._clear_all_sessions()
        return True
    
    @classmethod
    def _cleanup_expired_sessions(cls):
        """Remove expired sessions from storage"""
        now = datetime.now().timestamp()
        expired = [sid for sid, data in cls._sessions.items() if data["exp"] < now]
        for sid in expired:
            del cls._sessions[sid]
    
    @classmethod
    def generate_session(cls, password: str) -> str:
        """
        Generate a new session token based on password and expiration time
        """
        # Verify password first
        if not cls.app_config.verify_password(password):
            return ""
            
        # Clean up expired sessions
        cls._cleanup_expired_sessions()
        
        # Create session data
        expiry_date = datetime.now() + timedelta(days=3)
        session_id = secrets.token_hex(16)  # Generate random session ID
        
        # Store session data server-side
        cls._sessions[session_id] = {
            "exp": expiry_date.timestamp(),
            "pwd_ver": cls.app_config.password_hash[:8]  # Store truncated hash to detect password changes
        }
        
        # Create client token with just session ID and expiry
        token_data = {
            "sid": session_id,
            "exp": expiry_date.timestamp()
        }
        
        # Convert to JSON and encode
        json_data = json.dumps(token_data)
        encoded_data = base64.b64encode(json_data.encode()).decode()
        
        # Create signature using server-side key
        signature = hashlib.sha256((encoded_data + cls._get_session_key()).encode()).hexdigest()
        
        # Combine data and signature
        session_token = f"{encoded_data}.{signature}"
        return session_token
    
    @classmethod
    def verify_session(cls, session_token: str) -> bool:
        """
        Verify if a session token is valid
        """
        if not session_token:
            return False
            
        try:
            # Split token into data and signature
            parts = session_token.split('.')
            if len(parts) != 2:
                return False
                
            encoded_data, signature = parts
            
            # Verify signature using server-side key
            expected_signature = hashlib.sha256((encoded_data + cls._get_session_key()).encode()).hexdigest()
            if signature != expected_signature:
                return False
                
            # Decode data
            json_data = base64.b64decode(encoded_data).decode()
            token_data = json.loads(json_data)
            
            # Get session ID
            session_id = token_data.get("sid")
            if not session_id:
                return False
                
            # Get session data from server-side storage
            session_data = cls._sessions.get(session_id)
            if not session_data:
                return False
                
            # Check expiration
            if session_data["exp"] < datetime.now().timestamp():
                # Remove expired session
                del cls._sessions[session_id]
                return False
                
            # Check if password has changed since session was created
            if session_data["pwd_ver"] != cls.app_config.password_hash[:8]:
                return False
                
            # Return session ID for refresh
            return session_id
        except Exception:
            return False
                
    @classmethod
    def refresh_session(cls, session_token: str) -> bool:
        # Verify
        session_id = cls.verify_session(session_token)
        if not session_id:
            return False
            
        # Update expiry
        expiry_date = datetime.now() + timedelta(days=3)
        cls._sessions[session_id]["exp"] = expiry_date.timestamp()
        return True
        
            
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
    def update_and_restart_v2raypi(cls):
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'script', 'update_and_restart.sh')
        # Run script in a new session to ensure it survives service stop
        os.system(f'setsid {script_path} > /dev/null 2>&1 < /dev/null &')

    @classmethod
    def reboot_host(cls) -> bool:
        try:
            # Run reboot command in a new session to ensure it survives service stop
            os.system('setsid shutdown -r now > /dev/null 2>&1 < /dev/null &')
            return True
        except Exception:
            return False

    @classmethod
    def shutdown_host(cls) -> bool:
        try:
            # Run shutdown command in a new session to ensure it survives service stop
            os.system('setsid shutdown -h now > /dev/null 2>&1 < /dev/null &')
            return True
        except Exception:
            return False

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
            if cls.user_config.advance_config.geo_data.enabled():
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
    def get_v2raypi_recent_commits(cls) -> List[str]:
        try:
            cmd = ["git", "--no-pager", "log", "-n", "5", "--pretty=format:%ad|%s", "--date=format:%Y-%m-%d"]
            cwd = os.path.dirname(os.path.dirname(__file__))
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode != 0:
                return []

            commits = result.stdout.strip().split('\n')
            return commits
        except Exception:
            return []

    @classmethod
    def get_v2raypi_last_update_time(cls) -> str:
        try:
            cmd = ["git", "--no-pager", "log", "-1", "--pretty=format:%ad", "--date=format:%Y-%m-%d %H:%M:%S"]
            cwd = os.path.dirname(os.path.dirname(__file__))
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode != 0:
                print(f'Failed to get last update time, git log returned {result.returncode}')
                print(f'Error output: {result.stderr}')
                return ""

            output = result.stdout.strip()
            if not output:
                print('Git log output is empty')
                return ""

            return output
        except Exception as e:
            print(f'Exception in get_last_update_time: {str(e)}')
            return ""

    @classmethod
    def check_v2raypi_updates(cls) -> List[str]:
        try:
            cwd = os.path.dirname(os.path.dirname(__file__))
            
            # First fetch from remote
            fetch_cmd = ["git", "fetch"]
            fetch_result = subprocess.run(fetch_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if fetch_result.returncode != 0:
                return []

            # Get current branch name
            branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            branch_result = subprocess.run(branch_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if branch_result.returncode != 0:
                return []
            current_branch = branch_result.stdout.strip()

            # Get latest local commit date
            local_cmd = ["git", "--no-pager", "log", "-1", "--pretty=format:%at"]
            local_result = subprocess.run(local_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if local_result.returncode != 0:
                return []
            local_timestamp = int(local_result.stdout.strip())

            # Get commits that are in origin/<current_branch> but not in current branch
            cmd = ["git", "--no-pager", "log", f"HEAD..origin/{current_branch}", "--pretty=format:%at|%ad|%s", "--date=format:%Y-%m-%d"]
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode != 0:
                return []

            commits = []
            if result.stdout.strip():
                for commit in result.stdout.strip().split('\n'):
                    timestamp, date, message = commit.split('|')
                    if int(timestamp) > local_timestamp:
                        commits.append(f"{date}|{message}")
            return commits
        except Exception:
            return []

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