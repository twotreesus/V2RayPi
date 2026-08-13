#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#Check Root
[ $(id -u) != "0" ] && { echo "${CFAILURE}Error: You must be root to run this script${CEND}"; exit 1; }

cd /usr/local/V2RayPi
# Supervisor redirects stdout to a file, which makes Python fully buffer
# print(); -u keeps apply-node / reload messages visible in /var/log/v2raypi.
export PYTHONUNBUFFERED=1
exec /usr/local/V2RayPi/venv/bin/python -u /usr/local/V2RayPi/app.py
