import base64
import ipaddress
import json
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def _host_for_uri(host: str) -> str:
    try:
        if ipaddress.ip_address(host).version == 6:
            return '[{0}]'.format(host)
    except ValueError:
        pass
    return host


def _query(parsed):
    return parse_qs(parsed.query, keep_blank_values=True)


def _first(query, *keys, default=None):
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return default


def _enabled(value) -> bool:
    return str(value or '').lower() in ('1', 'true', 'yes')


def _name(parsed, host: str, port: int) -> str:
    return unquote(parsed.fragment) if parsed.fragment else '{0}:{1}'.format(host, port)


def _port(parsed, default=443) -> int:
    try:
        return parsed.port or default
    except ValueError as error:
        raise ValueError('Invalid node port') from error


def _transport_from_query(proxy: dict, query):
    network = _first(query, 'type', 'network', default='tcp')
    proxy['network'] = network
    path = _first(query, 'path')
    host = _first(query, 'host')
    if network == 'ws':
        options = {}
        if path:
            options['path'] = path
        if host:
            options['headers'] = {'Host': host}
        if options:
            proxy['ws-opts'] = options
    elif network == 'grpc':
        service_name = _first(query, 'serviceName', 'service-name')
        if service_name:
            proxy['grpc-opts'] = {'grpc-service-name': service_name}


def _transport_query(proxy: dict, query: list):
    network = proxy.get('network', 'tcp')
    query.append(('type', network))
    if network == 'ws':
        options = proxy.get('ws-opts') or {}
        if options.get('path'):
            query.append(('path', options['path']))
        headers = options.get('headers') or {}
        host = headers.get('Host') or headers.get('host')
        if host:
            query.append(('host', host))
    elif network == 'grpc':
        service_name = (proxy.get('grpc-opts') or {}).get('grpc-service-name')
        if service_name:
            query.append(('serviceName', service_name))


def _parse_vmess(uri: str) -> dict:
    encoded = uri[len('vmess://'):].split('#', 1)[0]
    try:
        data = json.loads(_decode_base64(encoded).decode('utf-8'))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid VMess URL') from error

    proxy = {
        'name': data.get('ps') or '{0}:{1}'.format(data.get('add', ''), data.get('port', '')),
        'type': 'vmess',
        'server': data.get('add', ''),
        'port': int(data.get('port') or 443),
        'uuid': data.get('id', ''),
        'alterId': int(data.get('aid') or 0),
        'cipher': data.get('scy') or 'auto',
        'network': data.get('net') or 'tcp',
        'udp': True,
    }
    if data.get('tls'):
        proxy['tls'] = True
    if data.get('sni'):
        proxy['servername'] = data['sni']
    if data.get('fp'):
        proxy['client-fingerprint'] = data['fp']
    if data.get('alpn'):
        proxy['alpn'] = [item for item in str(data['alpn']).split(',') if item]
    if proxy['network'] == 'ws':
        options = {}
        if data.get('path'):
            options['path'] = data['path']
        if data.get('host'):
            options['headers'] = {'Host': data['host']}
        if options:
            proxy['ws-opts'] = options
    elif proxy['network'] == 'grpc' and data.get('path'):
        proxy['grpc-opts'] = {'grpc-service-name': data['path']}
    return proxy


def _encode_vmess(proxy: dict) -> str:
    network = proxy.get('network', 'tcp')
    data = {
        'v': '2',
        'ps': proxy.get('name', ''),
        'add': proxy.get('server', ''),
        'port': str(proxy.get('port', 443)),
        'id': proxy.get('uuid', ''),
        'aid': str(proxy.get('alterId', 0)),
        'scy': proxy.get('cipher', 'auto'),
        'net': network,
        'type': 'none',
        'host': '',
        'path': '',
        'tls': 'tls' if proxy.get('tls') else '',
        'sni': proxy.get('servername', ''),
        'fp': proxy.get('client-fingerprint', ''),
        'alpn': ','.join(proxy.get('alpn') or []),
    }
    if network == 'ws':
        options = proxy.get('ws-opts') or {}
        data['path'] = options.get('path', '')
        headers = options.get('headers') or {}
        data['host'] = headers.get('Host') or headers.get('host') or ''
    elif network == 'grpc':
        data['path'] = (proxy.get('grpc-opts') or {}).get('grpc-service-name', '')
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False).encode('utf-8'),
    ).decode('ascii')
    return 'vmess://' + encoded


def _parse_vless(uri: str) -> dict:
    parsed = urlsplit(uri)
    host = parsed.hostname
    uuid = unquote(parsed.username or '')
    if not host or not uuid:
        raise ValueError('Invalid VLESS URL')
    port = _port(parsed)
    query = _query(parsed)
    security = _first(query, 'security', default='none')
    proxy = {
        'name': _name(parsed, host, port),
        'type': 'vless',
        'server': host,
        'port': port,
        'uuid': uuid,
        'udp': True,
    }
    if security in ('tls', 'reality'):
        proxy['tls'] = True
    if _first(query, 'sni', 'servername'):
        proxy['servername'] = _first(query, 'sni', 'servername')
    if _first(query, 'flow'):
        proxy['flow'] = _first(query, 'flow')
    if _first(query, 'fp'):
        proxy['client-fingerprint'] = _first(query, 'fp')
    if _enabled(_first(query, 'insecure', 'allowInsecure')):
        proxy['skip-cert-verify'] = True
    if security == 'reality':
        proxy['reality-opts'] = {
            'public-key': _first(query, 'pbk', 'public-key', default=''),
            'short-id': _first(query, 'sid', 'short-id', default=''),
        }
    alpn = _first(query, 'alpn')
    if alpn:
        proxy['alpn'] = [item for item in alpn.split(',') if item]
    _transport_from_query(proxy, query)
    return proxy


def _encode_vless(proxy: dict) -> str:
    query = [('encryption', proxy.get('encryption', 'none'))]
    reality = proxy.get('reality-opts') or {}
    if reality:
        query.append(('security', 'reality'))
        if reality.get('public-key'):
            query.append(('pbk', reality['public-key']))
        if reality.get('short-id'):
            query.append(('sid', reality['short-id']))
    elif proxy.get('tls'):
        query.append(('security', 'tls'))
    else:
        query.append(('security', 'none'))
    for field, key in (
        ('servername', 'sni'),
        ('flow', 'flow'),
        ('client-fingerprint', 'fp'),
    ):
        if proxy.get(field):
            query.append((key, proxy[field]))
    if proxy.get('skip-cert-verify'):
        query.append(('insecure', '1'))
    if proxy.get('alpn'):
        query.append(('alpn', ','.join(proxy['alpn'])))
    _transport_query(proxy, query)
    user = quote(str(proxy.get('uuid', '')), safe='')
    host = _host_for_uri(str(proxy.get('server', '')))
    return 'vless://{0}@{1}:{2}?{3}#{4}'.format(
        user, host, proxy.get('port', 443), urlencode(query),
        quote(str(proxy.get('name', '')), safe=''),
    )


def _parse_ss(uri: str) -> dict:
    body = uri[len('ss://'):]
    body, _, fragment = body.partition('#')
    body, _, query_text = body.partition('?')
    if '@' not in body:
        try:
            body = _decode_base64(body).decode('utf-8')
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError('Invalid Shadowsocks URL') from error
    userinfo, separator, host_port = body.rpartition('@')
    if not separator:
        raise ValueError('Invalid Shadowsocks URL')
    decoded_userinfo = unquote(userinfo)
    if ':' not in decoded_userinfo:
        try:
            decoded_userinfo = _decode_base64(decoded_userinfo).decode('utf-8')
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError('Invalid Shadowsocks credentials') from error
    method, separator, password = decoded_userinfo.partition(':')
    if not separator:
        raise ValueError('Invalid Shadowsocks credentials')
    parsed = urlsplit('ss://x@' + host_port)
    host = parsed.hostname
    if not host:
        raise ValueError('Invalid Shadowsocks server')
    port = _port(parsed)
    proxy = {
        'name': unquote(fragment) if fragment else '{0}:{1}'.format(host, port),
        'type': 'ss',
        'server': host,
        'port': port,
        'cipher': method,
        'password': password,
        'udp': True,
    }
    plugin = _first(parse_qs(query_text), 'plugin')
    if plugin:
        parts = plugin.split(';')
        proxy['plugin'] = parts[0]
        options = {}
        for part in parts[1:]:
            key, separator, value = part.partition('=')
            if separator:
                options[key] = value
        if options:
            proxy['plugin-opts'] = options
    return proxy


def _encode_ss(proxy: dict) -> str:
    credentials = '{0}:{1}'.format(
        proxy.get('cipher', ''),
        proxy.get('password', ''),
    )
    userinfo = _encode_base64(credentials.encode('utf-8'))
    host = _host_for_uri(str(proxy.get('server', '')))
    query = []
    if proxy.get('plugin'):
        plugin = [str(proxy['plugin'])]
        for key, value in (proxy.get('plugin-opts') or {}).items():
            plugin.append('{0}={1}'.format(key, value))
        query.append(('plugin', ';'.join(plugin)))
    suffix = '?' + urlencode(query) if query else ''
    return 'ss://{0}@{1}:{2}{3}#{4}'.format(
        userinfo, host, proxy.get('port', 443), suffix,
        quote(str(proxy.get('name', '')), safe=''),
    )


def _parse_trojan(uri: str) -> dict:
    parsed = urlsplit(uri)
    host = parsed.hostname
    password = unquote(parsed.username or '')
    if not host or not password:
        raise ValueError('Invalid Trojan URL')
    port = _port(parsed)
    query = _query(parsed)
    proxy = {
        'name': _name(parsed, host, port),
        'type': 'trojan',
        'server': host,
        'port': port,
        'password': password,
        'udp': True,
    }
    if _first(query, 'sni', 'peer'):
        proxy['sni'] = _first(query, 'sni', 'peer')
    if _enabled(_first(query, 'insecure', 'allowInsecure')):
        proxy['skip-cert-verify'] = True
    alpn = _first(query, 'alpn')
    if alpn:
        proxy['alpn'] = [item for item in alpn.split(',') if item]
    _transport_from_query(proxy, query)
    return proxy


def _encode_trojan(proxy: dict) -> str:
    query = []
    if proxy.get('sni'):
        query.append(('sni', proxy['sni']))
    if proxy.get('skip-cert-verify'):
        query.append(('insecure', '1'))
    if proxy.get('alpn'):
        query.append(('alpn', ','.join(proxy['alpn'])))
    _transport_query(proxy, query)
    return 'trojan://{0}@{1}:{2}?{3}#{4}'.format(
        quote(str(proxy.get('password', '')), safe=''),
        _host_for_uri(str(proxy.get('server', ''))),
        proxy.get('port', 443),
        urlencode(query),
        quote(str(proxy.get('name', '')), safe=''),
    )


def _parse_hysteria2(uri: str) -> dict:
    parsed = urlsplit(uri)
    host = parsed.hostname
    password = unquote(parsed.username or '')
    if not host or not password:
        raise ValueError('Invalid Hysteria2 URL')
    port = _port(parsed)
    query = _query(parsed)
    proxy = {
        'name': _name(parsed, host, port),
        'type': 'hysteria2',
        'server': host,
        'port': port,
        'password': password,
        'udp': True,
    }
    for field, keys in (
        ('sni', ('sni', 'peer')),
        ('obfs', ('obfs',)),
        ('obfs-password', ('obfs-password', 'obfs_password')),
        ('up', ('up',)),
        ('down', ('down',)),
        ('ports', ('mport', 'ports')),
        ('hop-interval', ('hop-interval', 'hop_interval')),
    ):
        value = _first(query, *keys)
        if value:
            proxy[field] = value
    if _enabled(_first(query, 'insecure')):
        proxy['skip-cert-verify'] = True
    alpn = _first(query, 'alpn')
    if alpn:
        proxy['alpn'] = [item for item in alpn.split(',') if item]
    return proxy


def _encode_hysteria2(proxy: dict) -> str:
    query = []
    for field, key in (
        ('sni', 'sni'),
        ('obfs', 'obfs'),
        ('obfs-password', 'obfs-password'),
        ('up', 'up'),
        ('down', 'down'),
        ('ports', 'mport'),
        ('hop-interval', 'hop-interval'),
    ):
        if proxy.get(field):
            query.append((key, proxy[field]))
    if proxy.get('skip-cert-verify'):
        query.append(('insecure', '1'))
    if proxy.get('alpn'):
        query.append(('alpn', ','.join(proxy['alpn'])))
    return 'hysteria2://{0}@{1}:{2}?{3}#{4}'.format(
        quote(str(proxy.get('password') or proxy.get('auth', '')), safe=''),
        _host_for_uri(str(proxy.get('server', ''))),
        proxy.get('port', 443),
        urlencode(query),
        quote(str(proxy.get('name', '')), safe=''),
    )


def _parse_anytls(uri: str) -> dict:
    parsed = urlsplit(uri)
    host = parsed.hostname
    password = unquote(parsed.username or '')
    if not host or not password:
        raise ValueError('Invalid AnyTLS URL')
    port = _port(parsed)
    query = _query(parsed)
    proxy = {
        'name': _name(parsed, host, port),
        'type': 'anytls',
        'server': host,
        'port': port,
        'password': password,
        'udp': True,
    }
    sni = _first(query, 'sni')
    if sni:
        proxy['sni'] = sni
    if _enabled(_first(query, 'insecure', 'allowInsecure')):
        proxy['skip-cert-verify'] = True
    return proxy


def _encode_anytls(proxy: dict) -> str:
    query = []
    if proxy.get('sni'):
        query.append(('sni', proxy['sni']))
    if proxy.get('skip-cert-verify'):
        query.append(('insecure', '1'))
    suffix = '?' + urlencode(query) if query else ''
    return 'anytls://{0}@{1}:{2}/{3}#{4}'.format(
        quote(str(proxy.get('password', '')), safe=''),
        _host_for_uri(str(proxy.get('server', ''))),
        proxy.get('port', 443),
        suffix,
        quote(str(proxy.get('name', '')), safe=''),
    )


def _parse_mieru(uri: str) -> dict:
    parsed = urlsplit(uri)
    host = parsed.hostname
    username = unquote(parsed.username or '')
    password = unquote(parsed.password or '')
    if not host or not username or not password:
        raise ValueError('Invalid Mieru URL')
    port = _port(parsed, 2999)
    query = _query(parsed)
    proxy = {
        'name': _name(parsed, host, port),
        'type': 'mieru',
        'server': host,
        'port': port,
        'username': username,
        'password': password,
        'transport': _first(query, 'transport', default='TCP').upper(),
        'udp': True,
    }
    for field, keys in (
        ('port-range', ('port-range', 'portRange')),
        ('multiplexing', ('multiplexing', 'multiplex')),
        ('handshake-mode', ('handshake-mode', 'handshakeMode')),
        ('traffic-pattern', ('traffic-pattern', 'trafficPattern')),
    ):
        value = _first(query, *keys)
        if value:
            proxy[field] = value
    return proxy


def _encode_mieru(proxy: dict) -> str:
    query = [('transport', proxy.get('transport', 'TCP'))]
    for field in (
        'port-range', 'multiplexing', 'handshake-mode', 'traffic-pattern',
    ):
        if proxy.get(field):
            query.append((field, proxy[field]))
    return 'mieru://{0}:{1}@{2}:{3}?{4}#{5}'.format(
        quote(str(proxy.get('username', '')), safe=''),
        quote(str(proxy.get('password', '')), safe=''),
        _host_for_uri(str(proxy.get('server', ''))),
        proxy.get('port', 2999),
        urlencode(query),
        quote(str(proxy.get('name', '')), safe=''),
    )


PARSERS = {
    'vmess': _parse_vmess,
    'vless': _parse_vless,
    'ss': _parse_ss,
    'trojan': _parse_trojan,
    'hysteria2': _parse_hysteria2,
    'hy2': _parse_hysteria2,
    'anytls': _parse_anytls,
    'mieru': _parse_mieru,
    'mierus': _parse_mieru,
}

ENCODERS = {
    'vmess': _encode_vmess,
    'vless': _encode_vless,
    'ss': _encode_ss,
    'trojan': _encode_trojan,
    'hysteria2': _encode_hysteria2,
    'hy2': _encode_hysteria2,
    'anytls': _encode_anytls,
    'mieru': _encode_mieru,
    'mierus': _encode_mieru,
}


def parse_node_uri(uri: str) -> dict:
    uri = (uri or '').strip()
    scheme = urlsplit(uri).scheme.lower()
    parser = PARSERS.get(scheme)
    if not parser:
        raise ValueError('Unsupported node URL scheme')
    proxy = parser(uri)
    required = ('name', 'type', 'server', 'port')
    if any(not proxy.get(field) for field in required):
        raise ValueError('Node URL is missing required fields')
    return proxy


def encode_node_uri(proxy: dict) -> str:
    proxy_type = (proxy or {}).get('type', '').lower()
    encoder = ENCODERS.get(proxy_type)
    if not encoder:
        raise ValueError('Node type cannot be shared as a URL: {0}'.format(
            proxy_type or 'unknown',
        ))
    return encoder(proxy)
