#!/bin/bash

brew update
brew install wget curl python3 v2ray

# pip force args
if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
    PIP_ARGS="--break-system-packages"
else
    PIP_ARGS=""
fi

pip3 install -r requirements.txt $PIP_ARGS
mkdir -p ~/Library/Logs/v2ray/
brew services start v2ray