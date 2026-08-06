# encoding: utf-8
"""
File:       node_item
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:32
Desc:
"""

from .base_data_item import BaseDataItem
import json
import base64
from urllib.parse import urlparse, parse_qs, unquote, quote, urlencode
from .keys import Keyword as K

class Node(BaseDataItem):
    def __init__(self):
        self.add = None
        self.aid = None
        self.host = None
        self.id = None
        self.net = None
        self.path = None
        self.port = None
        self.ps = None
        self.tls = None
        self.type = None
        self.v = None
        self.scy = None
        self.sni = None
        self.alpn = None
        self.protocol = 'vmess'
        self.flow = None
        self.pbk = None
        self.sid = None
        self.fp = None
        self.password = None
        # Mieru uses a username/password pair.  Keep these as flat fields so
        # loading and persistence remain compatible with the existing Node
        # model used by the other protocols.
        self.username = None
        self.port_bindings = None
        self.domain_name = None
        self.profile_name = None
        self.mtu = None
        self.multiplexing = None
        self.handshake_mode = None
        self.traffic_pattern = None
        self.skip_cert_verify = False
        self.obfs = None
        self.obfs_password = None
        self.up = None
        self.down = None
        self.ports = None
        self.hop_interval = None
        self.udp = True

    @property
    def link(self):
        if self.protocol == 'mieru':
            return self._mieru_link()
        if self.protocol == 'anytls':
            return self._anytls_link()
        if self.protocol == 'hysteria2':
            return self._hysteria2_link()
        if self.protocol == 'vless':
            return self._vless_link()
        if self.protocol == 'ss':
            return self._ss_link()
        data = self.dump()
        content = json.dumps(data)
        content = base64.b64encode(content.encode('utf8')).decode('utf8')
        return K.vmess_scheme + content

    def _mieru_link(self):
        """Serialize the simple Mieru sharing URI.

        The original Mieru standard sharing URI is not reconstructed here;
        preserving the simple URI gives manual nodes a safe round trip while
        the native client remains responsible for applying its JSON config.
        """
        username = quote(self.username or '', safe='')
        password = quote(self.password or '', safe='')
        netloc = '{}:{}@{}:{}'.format(username, password, self.add, self.port or 443)
        query = []
        bindings = self.port_bindings or []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            if binding.get('portRange') is not None:
                query.append(('port', binding.get('portRange')))
            elif binding.get('port') is not None:
                query.append(('port', binding.get('port')))
            if binding.get('protocol'):
                query.append(('protocol', binding.get('protocol')))
        if self.mtu is not None:
            query.append(('mtu', self.mtu))
        if self.multiplexing:
            query.append(('multiplexing', self.multiplexing))
        if self.handshake_mode:
            query.append(('handshake-mode', self.handshake_mode))
        if self.traffic_pattern:
            query.append(('traffic-pattern', self.traffic_pattern))
        if self.profile_name:
            query.append(('profile', self.profile_name))
        fragment = quote(self.ps or '', safe='')
        suffix = '?' + urlencode(query) if query else ''
        return '{}{}{}#{}'.format(K.mierus_scheme, netloc, suffix, fragment)

    @classmethod
    def mieru_uri_to_data(cls, url: str):
        """Parse Mieru simple sharing links (mierus:// and compatible mieru://).

        The native ``mieru://`` standard sharing link is intentionally left
        for the Mieru CLI/importer because it is an encoded native config,
        whereas ``mierus://`` is the human-readable form used by subscriptions.
        """
        if not url:
            return None
        url = url.strip()
        # ``mieru://`` is the native encoded sharing link.  It is not the
        # human-readable form parsed below; do not silently interpret its
        # payload as a hostname.
        if not url.startswith(K.mierus_scheme):
            return None

        parsed = urlparse(url)
        if not parsed.hostname:
            return None
        query = parse_qs(parsed.query, keep_blank_values=True)

        def values(*keys):
            result = []
            for key in keys:
                result.extend(query.get(key, []))
            return result

        def first(*keys):
            items = values(*keys)
            return unquote(items[0]) if items else None

        bindings = []
        ports = values('port', 'ports')
        port_ranges = values('portRange', 'port-range', 'port_range')
        protocols = values('protocol', 'protocols', 'transport')
        for index, port in enumerate(ports):
            port = unquote(port)
            binding = {
                'protocol': unquote(protocols[index]) if index < len(protocols) else 'TCP',
            }
            if '-' in port:
                binding['portRange'] = port
            else:
                binding['port'] = port
            bindings.append({
                **binding,
            })
        for index, port_range in enumerate(port_ranges):
            bindings.append({
                'portRange': unquote(port_range),
                'protocol': unquote(protocols[index]) if index < len(protocols) else 'TCP',
            })

        # For the common one-port form, retain the existing flat port field.
        port = parsed.port
        if port is None and ports:
            try:
                port = int(ports[0])
            except (TypeError, ValueError):
                port = 443
        port = port or 443
        username = unquote(parsed.username or '') or first('username', 'user')
        password = unquote(parsed.password or '') or first('password', 'pass')
        return {
            'protocol': 'mieru',
            'username': username or '',
            'password': password or '',
            'add': parsed.hostname,
            'port': port,
            'port_bindings': bindings or [{'port': str(port), 'protocol': first('protocol', 'transport') or 'TCP'}],
            'domain_name': first('domainName', 'domain-name'),
            'profile_name': first('profile'),
            'mtu': first('mtu'),
            'multiplexing': first('multiplexing', 'multiplex'),
            'handshake_mode': first('handshake-mode', 'handshakeMode'),
            'traffic_pattern': first('traffic-pattern', 'trafficPattern'),
            'udp': first('udp') not in ('0', 'false', 'False'),
            'ps': unquote(parsed.fragment) if parsed.fragment else '{}:{}'.format(parsed.hostname, port),
        }

    def _anytls_link(self):
        netloc = '{}@{}:{}'.format(self.password or '', self.add, self.port)
        q = []
        if self.sni:
            q.append(('sni', self.sni))
        if self.skip_cert_verify:
            q.append(('allowInsecure', '1'))
        frag = quote(self.ps or '', safe='')
        query = ('?' + urlencode(q)) if q else '/'
        return '{}://{}{}#{}'.format(K.anytls_scheme.rstrip('://'), netloc, query, frag)

    @classmethod
    def anytls_uri_to_data(cls, url: str):
        """Parse anytls:// URI into a dict suitable for Node().load_data(). Returns None if invalid."""
        if not url or not url.strip().startswith(K.anytls_scheme):
            return None
        url = url.strip()
        parsed = urlparse(url)
        netloc = parsed.netloc
        if '@' not in netloc:
            return None
        password, hostport = netloc.rsplit('@', 1)
        if ':' in hostport:
            host, port_str = hostport.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                return None
        else:
            host = hostport
            port = 443
        query = parse_qs(parsed.query, keep_blank_values=True)
        def first(k, default=None):
            return query.get(k, [default])[0] if query.get(k) else default
        return {
            'protocol': 'anytls',
            'password': password,
            'add': host,
            'port': port,
            'sni': first('sni') or host,
            'skip_cert_verify': first('allowInsecure') == '1',
            'ps': unquote(parsed.fragment) if parsed.fragment else '{}:{}'.format(host, port),
        }

    def _hysteria2_link(self):
        netloc = '{}@{}:{}'.format(quote(self.password or '', safe=''), self.add, self.port or 443)
        q = []
        if self.sni:
            q.append(('sni', self.sni))
        if self.skip_cert_verify:
            q.append(('insecure', '1'))
        if self.obfs:
            q.append(('obfs', self.obfs))
        if self.obfs_password:
            q.append(('obfs-password', self.obfs_password))
        if self.alpn:
            alpn = ','.join(self.alpn) if isinstance(self.alpn, list) else self.alpn
            q.append(('alpn', alpn))
        if self.up:
            q.append(('up', self.up))
        if self.down:
            q.append(('down', self.down))
        if self.ports:
            q.append(('mport', self.ports))
        if self.hop_interval:
            q.append(('hop-interval', self.hop_interval))
        frag = quote(self.ps or '', safe='')
        query = '?' + urlencode(q) if q else ''
        return '{}{}{}#{}'.format(K.hysteria2_scheme, netloc, query, frag)

    @classmethod
    def hysteria2_uri_to_data(cls, url: str):
        """Parse hysteria2:// or hy2:// URI into a dict suitable for Node().load_data()."""
        if not url:
            return None
        url = url.strip()
        if not (url.startswith(K.hysteria2_scheme) or url.startswith(K.hy2_scheme)):
            return None
        parsed = urlparse(url)
        if not parsed.hostname:
            return None
        query = parse_qs(parsed.query, keep_blank_values=True)
        def first(k, default=None):
            return query.get(k, [default])[0] if query.get(k) else default
        alpn = first('alpn')
        if alpn:
            alpn = [item.strip() for item in alpn.split(',') if item.strip()]
        return {
            'protocol': 'hysteria2',
            'password': unquote(parsed.username or ''),
            'add': parsed.hostname,
            'port': parsed.port or 443,
            'sni': first('sni') or first('peer') or parsed.hostname,
            'skip_cert_verify': first('insecure') in ('1', 'true', 'True'),
            'obfs': first('obfs'),
            'obfs_password': first('obfs-password') or first('obfs_password'),
            'alpn': alpn,
            'up': first('up'),
            'down': first('down'),
            'ports': first('mport') or first('ports'),
            'hop_interval': first('hop-interval') or first('hop_interval'),
            'ps': unquote(parsed.fragment) if parsed.fragment else '{}:{}'.format(parsed.hostname, parsed.port or 443),
        }

    def _vless_link(self):
        netloc = '{}@{}:{}'.format(self.id, self.add, self.port)
        q = []
        sec = self.tls or ('reality' if self.pbk else None)
        if sec:
            q.append(('security', sec))
        q.append(('encryption', 'none'))
        if self.pbk:
            q.append(('pbk', self.pbk))
        if self.fp:
            q.append(('fp', self.fp))
        if self.sni:
            q.append(('sni', self.sni))
        if self.host:
            q.append(('host', self.host))
        if self.path:
            q.append(('path', self.path))
        if self.sid:
            q.append(('sid', self.sid))
        if self.skip_cert_verify:
            q.append(('insecure', '1'))
        q.append(('headerType', getattr(self, 'headerType', None) or 'none'))
        q.append(('type', self.net or 'tcp'))
        if self.flow:
            q.append(('flow', self.flow))
        frag = unquote(self.ps) if self.ps else ''
        return '{}://{}?{}#{}'.format(K.vless_scheme.rstrip('://'), netloc, urlencode(q), frag)

    @classmethod
    def vless_uri_to_data(cls, url: str):
        """Parse vless:// URI into a dict suitable for Node().load_data(data). Returns None if invalid."""
        if not url or not url.strip().startswith(K.vless_scheme):
            return None
        url = url.strip()
        parsed = urlparse(url)
        netloc = parsed.netloc
        if '@' not in netloc:
            return None
        userinfo, hostport = netloc.rsplit('@', 1)
        uuid = userinfo
        if ':' in hostport:
            host, port_str = hostport.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                return None
        else:
            host = hostport
            port = 443
        query = parse_qs(parsed.query, keep_blank_values=True)
        def first(k, default=None):
            return query.get(k, [default])[0] if query.get(k) else default
        tls = first('security')
        sni = first('sni') or (host if tls else None)
        ws_host = first('host') or sni or host
        data = {
            'protocol': 'vless',
            'id': uuid,
            'add': host,
            'port': port,
            'ps': unquote(parsed.fragment) if parsed.fragment else (host + ':' + str(port)),
            'net': first('type') or 'tcp',
            'type': first('headerType') or 'none',
            'tls': tls,
            'sni': sni,
            'host': ws_host,
            'path': first('path') or '',
            'flow': first('flow'),
            'pbk': first('pbk'),
            'sid': first('sid'),
            'fp': first('fp') or 'chrome',
            'skip_cert_verify': first('insecure') in ('1', 'true', 'True') or first('allowInsecure') == '1',
        }
        return data

    def _ss_link(self):
        method = self.scy or 'aes-256-gcm'
        password = self.password or ''
        netloc = '{}:{}@{}:{}'.format(method, password, self.add, self.port)
        frag = quote(self.ps or '', safe='')
        return '{}://{}#{}'.format(K.ss_scheme.rstrip('://'), netloc, frag)

    @classmethod
    def ss_uri_to_data(cls, url: str):
        """Parse ss:// URI into a dict suitable for Node().load_data(). Returns None if invalid."""
        if not url or not url.strip().startswith(K.ss_scheme):
            return None
        url = url.strip()
        parsed = urlparse(url)
        netloc = parsed.netloc
        if '@' not in netloc:
            return None
        method_password, hostport = netloc.rsplit('@', 1)
        if ':' in method_password:
            method, password = method_password.split(':', 1)
        else:
            method = method_password
            password = ''
        if ':' in hostport:
            host, port_str = hostport.rsplit(':', 1)
            try:
                port = int(port_str)
            except ValueError:
                return None
        else:
            host = hostport
            port = 443
        return {
            'protocol': 'ss',
            'scy': method,
            'password': password,
            'add': host,
            'port': port,
            'ps': unquote(parsed.fragment) if parsed.fragment else '{}:{}'.format(host, port),
        }
