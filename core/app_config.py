# encoding: utf-8
"""
File:       config
Author:     twotrees.us@gmail.com
Date:       2020年7月25日  30周星期六 18:55
Desc:       Application configuration management
"""
import hashlib
from .base_data_item import BaseDataItem

class AppConfig(BaseDataItem):
    def __init__(self):
        self.port = 1086
        self.inited = False
        self.password_hash = hashlib.sha256('admin'.encode()).hexdigest()

    def load(self):
        obj = super().load()
        if obj == self:
            self.save()
        return obj

    def filename(self):
        return 'config/app_config.json'
        
    def verify_password(self, password):
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

    def _update_password(self, password):
        """Internal method to update password hash"""
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
        self.save()