#! /usr/bin/env python
# -*- coding: utf-8 -*-
import os
import json
import queue
import threading
import time
import functools
from flask import Flask, render_template, jsonify, request, Response, make_response
from werkzeug.serving import WSGIRequestHandler

from core.core_service import CoreService
from core.keys import Keyword as K
from core.mihomo_default_path import MihomoDefaultPath
from core.web_terminal import WebTerminalManager

dir_path = os.path.dirname(os.path.realpath(__file__))
os.chdir(dir_path)
CoreService.load()

app = Flask(__name__, static_url_path='/static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

web_terminal = WebTerminalManager()


class V2RayPiRequestHandler(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        if self.path.split('?', 1)[0] in ('/get_status', '/get_performance'):
            return
        super().log_request(code, size)


# Authentication decorator
def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # Skip auth for page routes
        if request.path.endswith('.html') or request.path == '/':
            return f(*args, **kwargs)

        # Check session in cookie or Authorization header
        session = request.cookies.get(K.session)
        if not session:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                session = auth_header[7:]
        if not session or not CoreService.verify_session(session):
            return jsonify({K.result: K.session_error, 'error': 'session_expired'})

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

@app.route('/system.html')
def system_page():
    return render_template("system.html")

@app.route('/api/update_password', methods=['POST'])
@require_auth
def update_password_api():
    result = K.failed
    data = request.get_json()
    if not data or 'current_password' not in data or 'new_password' not in data:
        return jsonify({
            K.result: result,
            'error': 'password_fields_required',
        })
    
    current_password = data['current_password']
    new_password = data['new_password']
    
    # update password
    if not CoreService.update_password(current_password, new_password):
        return jsonify({
            K.result: result,
            'error': 'current_password_invalid',
        })
        
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
    if CoreService.stop_mihomo():
        result = K.ok
    return jsonify({K.result: result})

@app.route('/restart_service')
@require_auth
def restart_service_api():
    result = K.failed
    if CoreService.restart_mihomo():
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

@app.route('/get_egress_ip')
@require_auth
def get_egress_ip_api():
    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    info = CoreService.get_egress_ip(force=force)
    payload = dict(info)
    payload[K.result] = K.ok if info.get('ok') else K.failed
    return jsonify(payload)

@app.route('/get_performance')
@require_auth
def get_performance_api():
    performance = CoreService.performance()
    performance.update({K.result: K.ok})
    return jsonify(performance)

@app.route('/check_mihomo_new_ver')
@require_auth
def check_mihomo_new_ver_api():
    version = CoreService.mihomo.check_new_version()
    return jsonify({
        K.result : K.ok,
        K.version : version})

@app.route('/update_mihomo')
@require_auth
def update_mihomo_api():
    success = CoreService.update_mihomo()
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
        name = request.args.get(K.name) or ''
        CoreService.add_subscribe(url, name)
        result = K.ok
    except:
        pass

    return jsonify({K.result : result})

@app.route('/rename_subscribe')
@require_auth
def rename_subscribe_api():
    result = K.failed
    try:
        url = request.args.get(K.subscribe)
        name = request.args.get(K.name) or ''
        CoreService.rename_subscribe(url, name)
        result = K.ok
    except:
        pass

    return jsonify({K.result: result})

@app.route('/favorite_node')
@require_auth
def favorite_node_api():
    result = K.failed
    try:
        url = request.args.get(K.subscribe)
        index = int(request.args.get(K.node_index, 0))
        added = CoreService.node_manager.favorite_node(url, index)
        result = K.ok if added else K.failed
    except:
        pass
    return jsonify({K.result: result})

@app.route('/add_manual_node', methods=['POST'])
@require_auth
def add_manual_node_api():
    try:
        data = request.get_json() or {}
        added = CoreService.node_manager.add_manual_node(data.get(K.url, ''))
        if not added:
            return jsonify({
                K.result: K.failed,
                'error': 'duplicate_favorite',
            })
        return jsonify({K.result: K.ok})
    except ValueError:
        return jsonify({K.result: K.failed, 'error': 'invalid_node_url'})

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
    status.update({K.result: result})
    return jsonify(status)

@app.route('/get_node_link')
@require_auth
def get_node_link_api():
    try:
        url = request.args.get(K.subscribe)
        index = int(request.args.get(K.node_index))
        link = CoreService.node_manager.find_node(url, index).link
        return jsonify({K.result: K.ok, K.node_link: link})
    except ValueError:
        return jsonify({
            K.result: K.failed,
            'error': 'unsupported_node_share',
        })

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

@app.route('/stream_logs')
@require_auth
def stream_logs_api():
    def generate():
        log_path = MihomoDefaultPath.log_file()

        def tail(path, n=10):
            try:
                import subprocess
                return subprocess.check_output(['tail', '-n', str(n), path]).decode('utf-8', errors='replace')
            except Exception:
                return ''

        def file_size(path):
            try:
                return os.path.getsize(path)
            except Exception:
                return 0

        # Send initial content
        yield 'event: mihomo\ndata: ' + json.dumps({'init': True, 'text': tail(log_path)}) + '\n\n'

        log_pos = file_size(log_path)

        while True:
            try:
                time.sleep(0.5)

                size = file_size(log_path)
                if size < log_pos:
                    log_pos = size
                elif size > log_pos:
                    with open(log_path, 'r', errors='replace') as f:
                        f.seek(log_pos)
                        new_text = f.read(size - log_pos)
                    log_pos = size
                    if new_text:
                        yield 'event: mihomo\ndata: ' + json.dumps({'init': False, 'text': new_text}) + '\n\n'

                yield ': heartbeat\n\n'

            except GeneratorExit:
                break
            except OSError:
                # The Homebrew service can rotate or briefly replace its log
                # between the size check and open. Keep the SSE connection
                # alive and resume from the current file on the next pass.
                log_pos = file_size(log_path)
                yield ': heartbeat\n\n'

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/update_and_restart_v2raypi')
@require_auth
def update_and_restart_v2raypi_api():
    try:
        branch = request.args.get('branch')
        CoreService.update_and_restart_v2raypi(branch)
        return jsonify({K.result: K.ok})
    except:
        return jsonify({K.result: K.failed})

@app.route('/get_v2raypi_branches')
@require_auth
def get_v2raypi_branches_api():
    try:
        info = CoreService.get_v2raypi_branches()
        return jsonify({K.result: K.ok, 'branches': info['branches'], 'current': info['current']})
    except Exception:
        return jsonify({K.result: K.failed})

@app.route('/get_v2raypi_recent_commits')
@require_auth
def get_v2raypi_recent_commits_api():
    try:
        branch = request.args.get('branch')
        commits = CoreService.get_v2raypi_recent_commits(branch)
        last_update = CoreService.get_v2raypi_last_update_time(branch)
        return jsonify({K.result: K.ok, 'commits': commits, 'last_update': last_update})
    except Exception:
        return jsonify({K.result: K.failed})

@app.route('/check_v2raypi_updates')
@require_auth
def check_v2raypi_updates_api():
    try:
        commits = CoreService.check_v2raypi_updates(request.args.get('branch'))
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

@app.route('/api/terminal/open', methods=['POST'])
@require_auth
def terminal_open_api():
    data = request.get_json(silent=True) or {}
    try:
        rows = int(data.get('rows') or 24)
        cols = int(data.get('cols') or 80)
    except (TypeError, ValueError):
        rows, cols = 24, 80
    try:
        session = web_terminal.create(rows=rows, cols=cols)
    except OSError as e:
        print(f'Failed to open web terminal: {e}')
        return jsonify({K.result: K.failed, 'error': 'terminal_open_failed'})
    return jsonify({K.result: K.ok, 'id': session.id})

@app.route('/api/terminal/stream')
@require_auth
def terminal_stream_api():
    session_id = request.args.get('id', '')
    session = web_terminal.get(session_id)
    if not session:
        return jsonify({K.result: K.failed, 'error': 'terminal_not_found'}), 404

    def generate():
        yield 'event: ready\ndata: {}\n\n'
        while True:
            try:
                chunk = session.output.get(timeout=0.8)
            except queue.Empty:
                if not session.alive:
                    break
                yield ': ping\n\n'
                continue
            if chunk is None:
                break
            yield 'event: output\ndata: ' + json.dumps({'data': chunk}) + '\n\n'
            if not session.alive and session.output.empty():
                break
        yield 'event: exit\ndata: {}\n\n'

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )

@app.route('/api/terminal/input', methods=['POST'])
@require_auth
def terminal_input_api():
    data = request.get_json(silent=True) or {}
    session = web_terminal.get(data.get('id', ''))
    if not session:
        return jsonify({K.result: K.failed, 'error': 'terminal_not_found'})
    text = data.get('data')
    if not isinstance(text, str):
        return jsonify({K.result: K.failed, 'error': 'invalid_input'})
    session.write(text, binary=bool(data.get('binary')))
    return jsonify({K.result: K.ok})

@app.route('/api/terminal/resize', methods=['POST'])
@require_auth
def terminal_resize_api():
    data = request.get_json(silent=True) or {}
    session = web_terminal.get(data.get('id', ''))
    if not session:
        return jsonify({K.result: K.failed, 'error': 'terminal_not_found'})
    try:
        rows = int(data.get('rows') or 24)
        cols = int(data.get('cols') or 80)
    except (TypeError, ValueError):
        return jsonify({K.result: K.failed, 'error': 'invalid_size'})
    session.resize(rows, cols)
    return jsonify({K.result: K.ok})

@app.route('/api/terminal/close', methods=['POST'])
@require_auth
def terminal_close_api():
    data = request.get_json(silent=True) or {}
    web_terminal.close(data.get('id', ''))
    return jsonify({K.result: K.ok})

@app.route('/export_config')
def export_config_api():
    session = request.cookies.get(K.session)
    if not session or not CoreService.verify_session(session):
        return jsonify({K.result: K.session_error, 'error': 'session_expired'})
    data = CoreService.export_config()
    from datetime import datetime
    filename = 'v2raypi-config-{}.zip'.format(datetime.now().strftime('%Y%m%d%H%M%S'))
    response = make_response(data)
    response.headers['Content-Type'] = 'application/zip'
    response.headers['Content-Disposition'] = 'attachment; filename={}'.format(filename)
    return response

@app.route('/import_config', methods=['POST'])
@require_auth
def import_config_api():
    if 'file' not in request.files:
        return jsonify({K.result: K.failed, 'error': 'file_required'})
    f = request.files['file']
    if not f.filename.endswith('.zip'):
        return jsonify({K.result: K.failed, 'error': 'zip_required'})
    try:
        data = f.read()
        if CoreService.import_config(data):
            return jsonify({K.result: K.ok})
        return jsonify({K.result: K.failed, 'error': 'invalid_backup'})
    except Exception:
        return jsonify({K.result: K.failed, 'error': 'import_failed'})

# Session check and refresh API
@app.route('/api/refresh')
@require_auth
def refresh_api():    
    # Refresh session
    session = request.cookies.get(K.session)
    if not CoreService.refresh_session(session):
        return jsonify({
            K.result: K.session_error,
            'error': 'session_expired',
        })
    
    return jsonify({ K.result: K.ok })

# Login API
@app.route('/api/login', methods=['POST'])
def login_api():
    result = K.failed
    data = request.get_json()
    if not data or K.password not in data:
        return jsonify({K.result: result, 'error': 'password_required'})
    
    password = data[K.password]
    
    # Generate session token
    session = CoreService.generate_session(password)
    if not session:
        return jsonify({K.result: result, 'error': 'invalid_password'})
    
    # Create response with session cookie
    response = make_response(jsonify({ K.result: K.ok }))
    response.set_cookie(K.session, session, max_age=30*24*60*60, httponly=True)
    
    return response

CoreService.performance_sample_start()
app.run(
    host='0.0.0.0',
    port=CoreService.app_config.port,
    request_handler=V2RayPiRequestHandler,
)
