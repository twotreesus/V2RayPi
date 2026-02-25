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
from urllib.parse import urlparse, parse_qs, unquote
from .keys import Keyword as K

def _node_protocol(node):
    return getattr(node, 'protocol', None) or 'vmess'

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
        self.protocol = None
        self.flow = None
        self.pbk = None
        self.sid = None
        self.fp = None

    @property
    def link(self):
        if _node_protocol(self) == 'vless':
            return self._vless_link()
        data = self.dump()
        content = json.dumps(data)
        content = base64.b64encode(content.encode('utf8')).decode('utf8')
        return K.vmess_scheme + content

    def _vless_link(self):
        from urllib.parse import urlencode
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
        if self.sid:
            q.append(('sid', self.sid))
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
            'host': sni or host,
            'path': first('path') or '',
            'flow': first('flow'),
            'pbk': first('pbk'),
            'sid': first('sid'),
            'fp': first('fp') or 'chrome',
        }
        return data