#! /usr/bin/env python
# -*- coding: utf-8 -*-
import os

import threading
import time
import functools
from flask import Flask, render_template, jsonify, request, Response, make_response

from core.core_service import CoreService
from core.keys import Keyword as K

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)
CoreService.load()

app = Flask(__name__, static_url_path='/static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Authentication decorator
def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth for page routes
        if request.path.endswith('.html') or request.path == '/':
            return f(*args, **kwargs)
            
        # Check session in cookie
        session = request.cookies.get(K.session)
        if not session or not CoreService.verify_session(session):
            return jsonify({K.result: K.session_error, 'message': 'Session invalid or expired'})
            
        return f(*args, **kwargs)
    return decorated

@app.route('/')
@app.route('/index.html')
def index_page():
    return render_template("index.html")

@app.route('/status.html')
def status_page():
    return render_template("status.html")

@app.route('/subscribe.html')
def subscribe_page():
    return render_template("subscribe.html")

@app.route('/advance.html')
def advance_page():
    return render_template("advance.html")

@app.route('/log.html')
def log_page():
    return render_template("log.html")

@app.route('/system.html')
def system_page():
    return render_template("system.html")

@app.route('/api/update_password', methods=['POST'])
@require_auth
def update_password_api():
    result = K.failed
    message = ''
    
    data = request.get_json()
    if not data or 'current_password' not in data or 'new_password' not in data:
        message = '当前密码和新密码不能为空'
        return jsonify({ K.result: result, 'message': message })
    
    current_password = data['current_password']
    new_password = data['new_password']
    
    # update password
    if not CoreService.update_password(current_password, new_password):
        message = '当前密码验证失败'
        return jsonify({ K.result: result, 'message': message })
        
    result = K.ok
    response = make_response(jsonify({ K.result: result, 'relogin': True }))
    
    return response

@app.route('/start_service')
@require_auth
def start_service_api():
    result = K.failed
    if CoreService.re_apply_node():
        result = K.ok

    return jsonify({ K.result : result })

@app.route('/stop_service')
@require_auth
def stop_service_api():
    result = K.failed
    if CoreService.stop_v2ray():
        result = K.ok
    return jsonify({K.result: result})

@app.route('/restart_service')
@require_auth
def restart_service_api():
    result = K.failed
    if CoreService.re_apply_node():
        result = K.ok
    return jsonify({K.result: result})

@app.route('/get_status')
@require_auth
def get_status_api():
    status = CoreService.status()
    status.update({K.result: K.ok})
    return jsonify(status)

@app.route('/get_system_status')
@require_auth
def get_system_status_api():
    status = CoreService.status()
    status.update({K.result: K.ok})
    return jsonify(status)

@app.route('/get_performance')
@require_auth
def get_performance_api():
    performance = CoreService.performance()
    performance.update({K.result: K.ok})
    return jsonify(performance)

@app.route('/check_v2ray_new_ver')
@require_auth
def check_v2ray_new_ver_api():
    version = CoreService.v2ray.check_new_version()
    return jsonify({
        K.result : K.ok,
        K.version : version})

@app.route('/update_v2ray')
@require_auth
def update_v2ray_api():
    success = CoreService.update_v2ray()
    result = K.failed
    if success:
        result = K.ok
    return jsonify({K.result:result})

@app.route('/switch_proxy_mode')
@require_auth
def switch_proxy_mode_api():
    mode = request.args.get('mode')
    mode = int(mode)
    success = CoreService.switch_mode(mode)
    result = K.failed
    if success:
        result = K.ok
    return jsonify({K.result: result})

@app.route('/add_subscribe')
@require_auth
def add_subscribe_api():
    result = K.failed
    try:
        url = request.args.get(K.subscribe)
        CoreService.add_subscribe(url)
        result = K.ok
    except:
        pass

    return jsonify({K.result : result})

@app.route('/add_manual_node')
@require_auth
def add_manual_node_api():
    result = K.failed
    try:
        url = request.args.get(K.url)
        CoreService.add_manual_node(url)
        result = K.ok
    except:
        pass

    return jsonify({K.result : result})

@app.route('/remove_subscribe')
@require_auth
def remove_subscribe_api():
    result = K.failed
    try:
        url = request.args.get(K.subscribe)
        CoreService.remove_subscribe(url)
        result = K.ok
    except:
        pass

    return jsonify({K.result: result})

@app.route('/update_all_subscribe')
def update_all_subscribe_api():
    result = K.failed
    try:
        CoreService.update_all_subscribe()
        result = K.ok
    except:
        pass
    return jsonify({K.result: result})

@app.route('/update_subscribe')
@require_auth
def update_subscribe_api():
    result = K.failed
    try:
        url = request.args.get(K.subscribe)
        CoreService.update_subscribe(url)
        result = K.ok
    except:
        pass
    return jsonify({K.result: result})

@app.route('/subscribe_list')
@require_auth
def subscribe_list_api():
    list = CoreService.node_manager.dump()
    status = CoreService.status()
    list.update(status)
    list.update({K.result : K.ok})
    return jsonify(list)

@app.route('/subscribe_ping_all')
@require_auth
def subscribe_ping_all_api():
    groups = CoreService.node_manager.ping_test_all()
    return jsonify({K.result : K.ok,
                    K.groups : groups})

@app.route('/apply_node')
@require_auth
def apply_node_api():
    url = request.args.get(K.subscribe)
    index = request.args.get(K.node_index)
    index = int(index)
    result = K.failed
    if CoreService.apply_node(url, index):
        result = K.ok

    # Get current running node info
    status = CoreService.status()
    return jsonify({
        K.result: result,
        K.ps: status.get(K.ps, None)
    })

@app.route('/get_node_link')
@require_auth
def get_node_link_api():
    url = request.args.get(K.subscribe)
    index = request.args.get(K.node_index)
    index = int(index)
    link = CoreService.node_manager.find_node(url, index).link
    return jsonify({ K.result: K.ok,
                     K.node_link: link})

@app.route('/delete_node')
@require_auth
def delete_node_api():
    url = request.args.get(K.subscribe)
    index = request.args.get(K.node_index)
    index = int(index)
    CoreService.delete_node(url, index)
    return jsonify({K.result: K.ok})

@app.route('/check_new_geo_data')
@require_auth
def check_geo_data_api():
    result = K.failed
    version = ''
    try:
        version = CoreService.check_new_geo_data()
        result = K.ok
    except:
        pass

    return jsonify({K.version: version,
                    K.result: result})

@app.route('/update_geo_data')
@require_auth
def update_geo_data_api():
    result = K.failed
    try:
        CoreService.update_geo_data()
        result = K.ok
    except:
        pass

    return jsonify({K.result: result})

@app.route('/get_advance_config')
@require_auth
def get_advance_config_api():
    config = CoreService.user_config.advance_config.dump(pure=False)
    result = {
        'advance_config': config,
        K.result: K.ok
    }
    return jsonify(result)

@app.route('/set_advance_config', methods=['POST'])
@require_auth
def set_advance_config_api():
    config = request.json
    code = K.failed
    result = CoreService.apply_advance_config(config)
    if result:
        code = K.ok
    return jsonify({ K.result : code })

@app.route('/reset_advance_config')
@require_auth
def reset_advance_config_api():
    code = K.failed
    result = CoreService.reset_advance_config()
    if result:
        code = K.ok
    return jsonify({ K.result : code })

@app.route('/make_policy')
@require_auth
def make_policy_api():
    contents:str = request.args.get(K.contents)
    content_list = contents.split('\n')
    type = request.args.get(K.type)
    outbound = request.args.get(K.outbound)
    policy = CoreService.make_policy(content_list, type, outbound)
    return Response(policy, mimetype='application/json')

@app.route('/get_access_log')
@require_auth
def get_access_log_api():
    return CoreService.v2ray.access_log()

@app.route('/get_error_log')
@require_auth
def get_error_log_api():
    return CoreService.v2ray.error_log()

@app.route('/update_and_restart_v2raypi')
@require_auth
def update_and_restart_v2raypi_api():
    try:
        CoreService.update_and_restart_v2raypi()
        return jsonify({K.result: K.ok})
    except:
        return jsonify({K.result: K.failed})

@app.route('/get_v2raypi_recent_commits')
@require_auth
def get_v2raypi_recent_commits_api():
    try:
        commits = CoreService.get_v2raypi_recent_commits()
        last_update = CoreService.get_v2raypi_last_update_time()
        return jsonify({K.result: K.ok, 'commits': commits, 'last_update': last_update})
    except Exception:
        return jsonify({K.result: K.failed})

@app.route('/check_v2raypi_updates')
@require_auth
def check_v2raypi_updates_api():
    try:
        commits = CoreService.check_v2raypi_updates()
        return jsonify({K.result: K.ok, 'commits': commits})
    except Exception:
        return jsonify({K.result: K.failed})

@app.route('/reboot_host')
@require_auth
def reboot_host_api():
    try:
        CoreService.reboot_host()
        return jsonify({K.result: K.ok})
    except Exception:
        return jsonify({K.result: K.failed})

@app.route('/shutdown_host')
@require_auth
def shutdown_host_api():
    try:
        CoreService.shutdown_host()
        return jsonify({K.result: K.ok})
    except Exception:
        return jsonify({K.result: K.failed})

# Session check and refresh API
@app.route('/api/refresh')
@require_auth
def refresh_api():    
    # Refresh session
    session = request.cookies.get(K.session)
    if not CoreService.refresh_session(session):
        return jsonify({ K.result: K.session_error })
    
    return jsonify({ K.result: K.ok })

# Login API
@app.route('/api/login', methods=['POST'])
def login_api():
    result = K.failed
    message = ''
    
    data = request.get_json()
    if not data or K.password not in data:
        message = 'Password is required'
        return jsonify({ K.result: result, 'message': message })
    
    password = data[K.password]
    
    # Generate session token
    session = CoreService.generate_session(password)
    if not session:
        message = 'Invalid password'
        return jsonify({ K.result: result, 'message': message })
    
    # Create response with session cookie
    response = make_response(jsonify({ K.result: K.ok }))
    response.set_cookie(K.session, session, max_age=30*24*60*60, httponly=True)
    
    return response

app.run(host='0.0.0.0', port=CoreService.app_config.port)
