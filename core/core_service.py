# encoding: utf-8
"""
File:       core_service
Author:     twotrees.us@gmail.com
Date:       2020年7月30日  31周星期四 10:55
Desc:
"""
import time
import os
import os.path
import platform
import re
import subprocess
from http.client import HTTPSConnection
from urllib.parse import urlparse
from .package import jsonpickle
from typing import List, Dict, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import *
import random
import time
import threading
import hashlib
import base64
import json
from datetime import datetime, timedelta
import secrets

from .app_config import AppConfig
from .mihomo_controller import MihomoController, make_controller
from .node_manager import NodeManager
from .keys import Keyword as K
from .mihomo_user_config import MihomoUserConfig
from .node import Node
from .performance_history import PerformanceHistory
from .traffic_monitor import TrafficMonitor
from .egress_ip import EgressIpResolver
from .api_serial import api_serial

class CoreService:
    app_config : AppConfig = None
    user_config: MihomoUserConfig = MihomoUserConfig()
    mihomo:MihomoController = make_controller()
    node_manager:NodeManager = NodeManager()
    traffic_monitor = TrafficMonitor()
    performance_history = PerformanceHistory()
    egress_ip_resolver = EgressIpResolver()
    scheduler:BackgroundScheduler = BackgroundScheduler(
        {
            'apscheduler.executors.default': {
                'class': 'apscheduler.executors.pool:ThreadPoolExecutor',
                # Performance sampling must keep its 1s cadence even while
                # auto-detect is blocked on network probes.
                'max_workers': '2'
            }
        })

    @classmethod
    def load(cls):
        config_path = 'config/'
        if not os.path.exists(config_path):
            os.mkdir(config_path)

        cls.app_config = AppConfig().load()
        cls.node_manager = NodeManager().load()
        cls.user_config = MihomoUserConfig().load()
        cls.user_config.advance_config.auto_detect.apply_fixed_defaults()

        # A node selected before the move to mihomo has no Clash payload to hand
        # to the core, so treat it as no selection rather than repeatedly failing
        # to apply it.
        if not getattr(cls.user_config.node, 'clash', None):
            cls.user_config.node = Node()

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
        running = cls.mihomo.running()
        version = cls.mihomo.version()

        result = {
            K.running: running,
            K.started_at: cls.mihomo.started_at() if running else None,
            K.version: version,
            K.proxy_mode: cls.user_config.proxy_mode,
        }

        node = cls.user_config.node.dump()
        result.update(node)
        result['airport'] = cls.node_manager.airport_name_for_node(
            cls.user_config.node,
        )
        return result

    @classmethod
    def get_egress_ip(cls, force: bool = False) -> dict:
        info = dict(cls.egress_ip_resolver.get(force=force))
        if not info.get('ok'):
            info['latency_ms'] = None
            return info
        if 'latency_ms' not in info:
            info['latency_ms'] = cls._probe_auto_detect_latency()
            cls.egress_ip_resolver.update_cache(info)
        return info

    @classmethod
    def _head_after_connect(cls, url: str, timeout) -> int:
        url = (url or '').strip()
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname:
            raise ValueError('probe URL must be https')
        path = parsed.path or '/'
        if parsed.query:
            path = '{0}?{1}'.format(path, parsed.query)
        conn = HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=timeout,
        )
        try:
            conn.connect()
            started = time.monotonic()
            conn.request('HEAD', path)
            conn.getresponse().read()
            return max(0, int(round((time.monotonic() - started) * 1000)))
        finally:
            conn.close()

    @classmethod
    def _probe_auto_detect_latency(cls) -> Optional[int]:
        detect = cls.user_config.advance_config.auto_detect
        try:
            latency_ms = cls._head_after_connect(detect.detect_url, detect.timeout)
        except Exception as e:
            print('egress latency probe failed, detail:\n{0}'.format(e))
            return None
        print('egress latency probe delay={0}ms'.format(latency_ms))
        return latency_ms

    @classmethod
    def invalidate_egress_ip(cls) -> None:
        cls.egress_ip_resolver.invalidate()

    @classmethod
    def update_and_restart_v2raypi(cls, branch: str = None):
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'script', 'update_and_restart.sh')
        if branch and not cls.is_valid_branch_name(branch):
            print(f'Refused to update, invalid branch name: {branch}')
            return
        target = f' {branch}' if branch else ''
        print(f'Updating V2RayPi, target branch: {branch or "current"}')
        # Run script in a new session to ensure it survives service stop
        os.system(f'setsid {script_path}{target} > /dev/null 2>&1 < /dev/null &')

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
        # Everything here was measured by the sampling job, so that every poller,
        # whatever its cadence, sees the same numbers over the same interval and
        # the charts keep their history across page loads.
        result = cls.performance_history.snapshot()

        # On a transparent side-router, system-wide counters mix the LAN
        # client side with the proxy's upstream side.  TrafficMonitor reads
        # counters installed at the client-facing iptables boundaries instead.
        result['network'] = cls.traffic_monitor.latest()

        return result

    @classmethod
    def add_subscribe(cls, url, name: str = ''):
        cls.node_manager.add_subscribe(url, name)
        cls.re_apply_node()

    @classmethod
    def rename_subscribe(cls, url, name: str):
        cls.node_manager.rename_subscribe(url, name)

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
    def delete_node(cls, url, index):
        # Only the selected node is written into mihomo's proxies list, so
        # removing an entry from the catalogue does not change the running
        # config and must not restart the service.
        cls.node_manager.delete_node(url, index)

    @classmethod
    def re_apply_node(cls, restart_auto_detect=True) -> bool:
        if not cls.user_config.node.add:
            return True

        result = cls.mihomo.apply_node(
            cls.user_config,
            cls.node_manager.all_nodes(),
            cls.node_manager.subscribe_hosts(),
        )
        if result:
            # The first successful node application enables TPROXY.  The
            # controller checks the systemd service state, so this is safe to
            # call on every subsequent node application and after reinstall.
            cls.mihomo.enable_iptables()
            # Node / mode changes can move the egress address; drop the cache
            # so the next Status lookup does not reuse a stale public IP.
            cls.invalidate_egress_ip()
        if restart_auto_detect:
            cls.restart_auto_detect()
        return result

    @classmethod
    def restart_auto_detect(cls):
        cls.auto_detect_cancel()
        if cls.user_config.advance_config.auto_detect.enabled :
            cls.auto_detect_start()

    @classmethod
    def stop_mihomo(cls) -> bool:
        result = cls.mihomo.stop()
        cls.auto_detect_cancel()

        return result

    @classmethod
    def restart_mihomo(cls) -> bool:
        result = cls.mihomo.restart()
        if result:
            cls.invalidate_egress_ip()
            cls.restart_auto_detect()
        return result

    @classmethod
    def apply_node(cls, url:str, index: int, restart_auto_detect=True) -> bool:
        result = False
        node = cls.node_manager.find_node(url, index)
        cls.user_config.node = node
        if cls.re_apply_node(restart_auto_detect):
            if restart_auto_detect:
                detect = cls.user_config.advance_config.auto_detect
                detect.last_switch_time = ''
                detect.last_probe_time = ''
                detect.last_probe_ok = True
                detect.last_probe_delay_ms = 0
            cls.user_config.save()
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
    def update_mihomo(cls) -> bool:
        result = True
        result = cls.mihomo.update()
        if result:
            if cls.user_config.advance_config.geo_data.enabled():
                cls.update_geo_data()

        return result

    @classmethod
    def check_new_geo_data(cls) -> str:
        check_url = cls.user_config.advance_config.geo_data.check_url
        new_version = cls.mihomo.check_new_geo_data(check_url)
        return new_version

    @classmethod
    def update_geo_data(cls):
        check_url = cls.user_config.advance_config.geo_data.check_url
        new_version = cls.mihomo.check_new_geo_data(check_url)

        cls.mihomo.update_geo_data(check_url)
        cls.user_config.advance_config.geo_data.current_version = new_version
        cls.user_config.save()

    @classmethod
    def apply_advance_config(cls, config:dict):
        result = True
        new_advance = cls.user_config.advance_config.load_data(config)
        new_advance.auto_detect.apply_fixed_defaults()
        cls.user_config.advance_config = new_advance
        result = cls.re_apply_node()
        if result:
            cls.user_config.save()
        return  result

    @classmethod
    def reset_advance_config(cls):
        result = True
        cls.user_config.advance_config = MihomoUserConfig.AdvanceConfig()
        result = cls.re_apply_node()
        if result:
            cls.user_config.save()
        return result

    @classmethod
    def make_policy(cls, contents:List[str], type:str, outbound:str) -> dict:
        type = MihomoUserConfig.AdvanceConfig.Policy.Type[type]
        outbound = MihomoUserConfig.AdvanceConfig.Policy.Outbound[outbound]
        policy = MihomoUserConfig.AdvanceConfig.Policy()
        policy.contents = contents
        policy.type = type.name
        policy.outbound = outbound.name
        return jsonpickle.encode(policy, indent=4)

    @classmethod
    def get_current_branch(cls) -> str:
        try:
            cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            cwd = os.path.dirname(os.path.dirname(__file__))
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            return result.stdout.strip() if result.returncode == 0 else ''
        except Exception as e:
            print(f'Exception in get_current_branch: {str(e)}')
            return ''

    @classmethod
    def resolve_local_rev(cls, branch: str = None) -> str:
        # Read history without touching the network: HEAD for the checked-out
        # branch, otherwise the local remote-tracking ref for the target branch.
        if not branch or not cls.is_valid_branch_name(branch):
            return "HEAD"
        if branch == cls.get_current_branch():
            return "HEAD"
        return f"origin/{branch}"

    @classmethod
    def get_v2raypi_recent_commits(cls, branch: str = None) -> List[str]:
        try:
            rev = cls.resolve_local_rev(branch)
            cmd = ["git", "--no-pager", "log", "-n", "5", "--pretty=format:%ad|%s", "--date=format:%Y-%m-%d", rev, "--"]
            cwd = os.path.dirname(os.path.dirname(__file__))
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            
            if result.returncode != 0:
                return []

            commits = result.stdout.strip().split('\n')
            return commits
        except Exception:
            return []

    @classmethod
    def get_v2raypi_last_update_time(cls, branch: str = None) -> str:
        try:
            rev = cls.resolve_local_rev(branch)
            cmd = ["git", "--no-pager", "log", "-1", "--pretty=format:%ad", "--date=format:%Y-%m-%d %H:%M:%S", rev, "--"]
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
    def is_valid_branch_name(cls, branch: str) -> bool:
        return bool(re.fullmatch(r'[A-Za-z0-9._/-]+', branch or ''))

    ORIGIN_FETCH_ALL_BRANCHES = '+refs/heads/*:refs/remotes/origin/*'

    @classmethod
    def ensure_origin_fetches_all_branches(cls, cwd: str) -> None:
        # One-click install uses `git clone --depth 1`, which implies
        # single-branch. Widen the fetch refspec so other remote tips
        # (dev, master, …) become visible to listing and updates.
        get_cmd = ['git', 'config', '--get-all', 'remote.origin.fetch']
        get_result = subprocess.run(
            get_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        specs = [
            line.strip() for line in (get_result.stdout or '').splitlines()
            if line.strip()
        ]
        if cls.ORIGIN_FETCH_ALL_BRANCHES in specs:
            return

        set_cmd = [
            'git', 'config', 'remote.origin.fetch',
            cls.ORIGIN_FETCH_ALL_BRANCHES,
        ]
        set_result = subprocess.run(
            set_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if set_result.returncode != 0:
            print(
                'Failed to widen remote.origin.fetch, git config returned '
                f'{set_result.returncode}'
            )
            print(f'Error output: {set_result.stderr}')

    @classmethod
    def get_v2raypi_branches(cls) -> Dict[str, Any]:
        try:
            cwd = os.path.dirname(os.path.dirname(__file__))

            cls.ensure_origin_fetches_all_branches(cwd)
            fetch_cmd = ["git", "fetch", "--prune"]
            fetch_result = subprocess.run(fetch_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if fetch_result.returncode != 0:
                print(f'Failed to fetch branches, git fetch returned {fetch_result.returncode}')
                print(f'Error output: {fetch_result.stderr}')

            list_cmd = ["git", "branch", "-r", "--format=%(refname:short)"]
            list_result = subprocess.run(list_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if list_result.returncode != 0:
                print(f'Failed to list branches, git branch returned {list_result.returncode}')
                print(f'Error output: {list_result.stderr}')
                return {'branches': [], 'current': ''}

            branches = []
            for ref in list_result.stdout.strip().split('\n'):
                ref = ref.strip()
                if not ref.startswith('origin/') or '->' in ref:
                    continue
                name = ref[len('origin/'):]
                if name != 'HEAD' and name not in branches:
                    branches.append(name)

            branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
            branch_result = subprocess.run(branch_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            current = branch_result.stdout.strip() if branch_result.returncode == 0 else ''

            if current and current not in branches:
                branches.append(current)

            return {'branches': branches, 'current': current}
        except Exception as e:
            print(f'Exception in get_v2raypi_branches: {str(e)}')
            return {'branches': [], 'current': ''}

    @classmethod
    def check_v2raypi_updates(cls, branch: str = None) -> List[str]:
        try:
            cwd = os.path.dirname(os.path.dirname(__file__))

            cls.ensure_origin_fetches_all_branches(cwd)
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

            if branch and not cls.is_valid_branch_name(branch):
                print(f'Refused to check updates, invalid branch name: {branch}')
                return []
            target_branch = branch or current_branch

            # Get latest local commit date
            local_cmd = ["git", "--no-pager", "log", "-1", "--pretty=format:%at"]
            local_result = subprocess.run(local_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            if local_result.returncode != 0:
                return []
            local_timestamp = int(local_result.stdout.strip())

            # Get commits that are in origin/<target_branch> but not in current branch
            cmd = ["git", "--no-pager", "log", f"HEAD..origin/{target_branch}", "--pretty=format:%at|%ad|%s", "--date=format:%Y-%m-%d"]
            result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

            if result.returncode != 0:
                print(f'Failed to check updates for {target_branch}, git log returned {result.returncode}')
                print(f'Error output: {result.stderr}')
                return []

            # Commits older than local HEAD are only noise when tracking the same
            # branch; across branches they are genuinely missing locally.
            same_branch = target_branch == current_branch

            commits = []
            if result.stdout.strip():
                for commit in result.stdout.strip().split('\n'):
                    timestamp, date, message = commit.split('|', 2)
                    if not same_branch or int(timestamp) > local_timestamp:
                        commits.append(f"{date}|{message}")
            return commits
        except Exception:
            return []

    PERFORMANCE_SAMPLE_SPAN = 1

    @classmethod
    def performance_sample_start(cls):
        cls.scheduler.add_job(
            CoreService.performance_sample_job,
            trigger='interval',
            seconds=cls.PERFORMANCE_SAMPLE_SPAN,
            id=K.performance_sample,
            replace_existing=True,
            max_instances=1,
            coalesce=True)
        if cls.scheduler.state is not STATE_RUNNING :
            cls.scheduler.start()

    @classmethod
    def performance_sample_job(cls):
        try:
            # The traffic rate defines the interval this sample covers, so it is
            # measured first and handed to the window.
            network = cls.traffic_monitor.poll()
            cls.performance_history.sample(network)
        except Exception as e:
            print(f'Performance sampling failed: {e}')

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
        def snapshot():
            detect = cls.user_config.advance_config.auto_detect
            return {
                'generation': api_serial.generation,
                'detect_url': detect.detect_url,
                'timeout': detect.timeout,
                'failed_count': detect.failed_count,
            }

        snap = api_serial.submit_read(snapshot)

        delay_ms = 0
        probe_ok = False
        retries = max(0, int(snap['failed_count']))
        for attempt in range(retries + 1):
            try:
                delay_ms = cls._head_after_connect(
                    snap['detect_url'],
                    snap['timeout'],
                )
            except Exception as e:
                if attempt < retries:
                    time.sleep(1 * (2 ** attempt))
                    continue
                print('detected connection failed, detail:\n{0}'.format(e))
            else:
                print('detected connection success, delay={0}ms'.format(delay_ms))
                probe_ok = True
            break

        def commit():
            if snap['generation'] != api_serial.generation:
                print('Auto switch skipped: configuration changed during probe')
                return
            detect = cls.user_config.advance_config.auto_detect
            if probe_ok:
                cls._record_last_probe(detect, True, delay_ms)
                cls.user_config.save()
                return

            cls._record_last_probe(detect, False)
            alternatives = []
            current = cls.user_config.node
            current_identity = (current.protocol, current.add, current.port, current.ps)
            for node_index, node in enumerate(cls.node_manager.manual_nodes):
                identity = (node.protocol, node.add, node.port, node.ps)
                if identity == current_identity:
                    continue
                alternatives.append((K.manual, node_index, node))
            if not alternatives:
                print('Auto switch skipped: no alternative favorite node is available')
                cls.user_config.save()
                return

            group_key, node_index, node = random.choice(alternatives)
            if not cls.apply_node(group_key, node_index, restart_auto_detect=False):
                print('Auto switch failed while applying node: {0}'.format(node.ps))
                cls.user_config.save()
                return

            detect.last_switch_time = cls._format_last_switch(node)
            cls.user_config.save()

        api_serial.submit_write(commit)

    @classmethod
    def _record_last_probe(cls, detect, ok, delay_ms=0):
        detect.last_probe_time = datetime.fromtimestamp(time.time()).strftime(
            '%Y-%m-%d %H:%M:%S',
        )
        detect.last_probe_ok = bool(ok)
        detect.last_probe_delay_ms = delay_ms if ok else 0

    @classmethod
    def _format_last_switch(cls, node) -> str:
        stamp = datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
        airport = (getattr(node, 'airport', None) or '').strip()
        if not airport:
            resolver = getattr(cls.node_manager, 'airport_name_for_node', None)
            if callable(resolver):
                airport = (resolver(node) or '').strip()
        if airport:
            return '{0} ---- {1} ---- {2}'.format(stamp, airport, node.ps)
        return '{0} ---- {1}'.format(stamp, node.ps)

    @classmethod
    def export_config(cls) -> str:
        import zipfile, io
        buf = io.BytesIO()
        config_dir = 'config'
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(config_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    zf.write(fpath, fpath)
        buf.seek(0)
        return buf.read()

    @classmethod
    def import_config(cls, zip_data: bytes) -> bool:
        import zipfile, io, tempfile, shutil
        try:
            tmpdir = tempfile.mkdtemp(prefix='v2raypi_backup_')
            buf = io.BytesIO(zip_data)
            with zipfile.ZipFile(buf, 'r') as zf:
                zf.extractall(tmpdir)
            for root, _, files in os.walk(tmpdir):
                for fname in files:
                    src = os.path.join(root, fname)
                    dst = os.path.join('config', fname)
                    shutil.move(src, dst)
            shutil.rmtree(tmpdir)
            cls.load()
            return True
        except Exception:
            return False
