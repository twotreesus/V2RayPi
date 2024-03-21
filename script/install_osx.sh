#!/usr/local/bin/bash

brew update
brew install wget curl python3 v2ray
pip3 install -r requirements.txt
mkdir -p ~/Library/Logs/v2ray/
brew services start v2ray