# encoding: utf-8
"""
File:       node
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:32
Desc:
"""

from .base_data_item import BaseDataItem
from .node_uri import encode_node_uri


class Node(BaseDataItem):
    """A single proxy from a Clash subscription.

    The original Clash proxy mapping is kept verbatim so it can be handed to
    mihomo without per-protocol field translation.  The flat fields alongside
    it are the fields used by the web UI.
    """

    def __init__(self):
        self.clash = {}
        self.ps = None
        self.add = None
        self.port = None
        self.protocol = None

    @classmethod
    def from_clash(cls, proxy: dict) -> 'Node':
        node = cls()
        node.clash = dict(proxy)
        node.ps = proxy.get('name', '')
        node.add = proxy.get('server', '')
        node.port = proxy.get('port', 0)
        node.protocol = proxy.get('type', '')
        return node

    @property
    def link(self) -> str:
        if not self.clash:
            return ''
        return encode_node_uri(self.clash)
