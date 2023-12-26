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

    @property
    def link(self):
        data = self.dump()
        content = json.dumps(data)
        content = base64.b64encode(content.encode('utf8')).decode('utf8')
        link = K.vmess_scheme
        link += content
        return link