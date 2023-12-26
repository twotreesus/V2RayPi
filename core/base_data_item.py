# encoding: utf-8
"""
File:       base_data_item
Author:     twotrees.us@gmail.com
Date:       2020年7月29日  31周星期三 21:45
Desc:
"""
import json
import os
import os.path
from .package import jsonpickle
import collections

class BaseDataItem:
    def filename(self):
        return ''

    def dump(self, pure=True):
        data = json.loads(jsonpickle.encode(self, unpicklable=not pure))
        return data

    def load(self):
        if os.path.exists(self.filename()):
            with open(self.filename()) as f:
                return jsonpickle.decode(f.read())
        return self

    def load_data(self, data: dict):
        pickle_data: dict = self.dump(pure=False)
        pickle_data = self._deep_update(pickle_data, data)
        return jsonpickle.decode(json.dumps(pickle_data))

    def save(self):
        raw = jsonpickle.encode(self, indent=4)
        with open(self.filename(), 'w+') as f:
            f.write(raw)
        os.sync()

    def _deep_update(self, dct, merge_dct, add_keys=False):
        dct = dct.copy()
        if not add_keys:
            merge_dct = {
                k: merge_dct[k]
                for k in set(dct).intersection(set(merge_dct))
            }

        for k, v in merge_dct.items():
            if (k in dct and isinstance(dct[k], dict)
                    and isinstance(merge_dct[k], collections.Mapping)):
                dct[k] = self._deep_update(dct[k], merge_dct[k], add_keys=add_keys)
            else:
                dct[k] = merge_dct[k]

        return dct