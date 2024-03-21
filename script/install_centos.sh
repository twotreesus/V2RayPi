###
 # @Author: Ziheng
 # @Date: 2021-06-27 02:07:58
 # @LastEditTime: 2021-06-27 02:12:32
###
#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#check Root
[ $(id -u) != "0" ] && { echo "${CFAILURE}Error: You must be root to run this script${CEND}"; exit 1; }

#install Needed Packages
yum update -y
yum install wget curl socat git python3-devel python3-setuptools python3-dev python3-pip python3-wheel openssl libssl-dev ca-certificates supervisor -y
pip3 install --upgrade setuptools
pip3 install wheel
pip3 install -r requirements.txt

#enable rc.local
cat>/etc/rc.local<<-EOF
#!/bin/sh -e
#
# rc.local
#
# This script is executed at the end of each multiuser runlevel.
# Make sure that the script will "exit 0" on success or any other
# value on error.
#
# In order to enable or disable this script just change the execution
# bits.
#
# By default this script does nothing.
if [ ! -d "/var/log/v2ray" ]; then
    mkdir /var/log/v2ray
fi
exit 0
EOF

# install v2ray
mkdir -p /etc/v2ray/
touch /etc/v2ray/config.json
chmod 644 /etc/v2ray/config.json
mkdir -p /var/log/v2ray/
bash update_v2ray.sh

#configure Supervisor
mkdir /etc/supervisor
mkdir /etc/supervisor/conf.d
echo_supervisord_conf > /etc/supervisor/supervisord.conf
cat>>/etc/supervisor/supervisord.conf<<EOF
[include]
files = /etc/supervisor/conf.d/*.ini
EOF
touch /etc/supervisor/conf.d/v2raypi.ini
cat>/etc/supervisor/conf.d/v2raypi.ini<<-EOF
[program:v2raypi]
command=/usr/local/V2RayPi/script/start.sh run
stdout_logfile=/var/log/v2raypi
autostart=true
autorestart=true
startsecs=5
priority=1
stopasgroup=true
killasgroup=true
EOF

supervisord -c /etc/supervisor/supervisord.conf
supervisorctl restart v2raypi

# ip table
echo net.ipv4.ip_forward=1 >> /etc/sysctl.conf && sysctl -p
cat>/etc/systemd/system/v2ray_iptable.service<<-EOF
[Unit]
Description=Tproxy rule
After=network-online.target
Wants=network-online.target

[Service]

Type=oneshot
ExecStart=/bin/bash /usr/local/V2RayPi/script/config_iptable.sh

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl disable v2ray_iptable.service

# 
chmod +x /etc/rc.local
systemctl start rc-local
systemctl status rc-local --no-pager
sync

echo "install success"
