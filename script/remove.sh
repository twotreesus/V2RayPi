#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

#check Root
[ $(id -u) != "0" ] && { echo "${CFAILURE}Error: You must be root to run this script${CEND}"; exit 1; }


# stop v2raypi
supervisorctl stop v2raypi
rm /etc/supervisor/conf.d/v2raypi.ini
supervisorctl reread

# remove v2raypi
rm -rf /usr/local/V2RayPi/
rm /var/log/v2raypi

# remove iptable service
systemctl stop v2ray_iptable.service
systemctl disable v2ray_iptable.service
rm /etc/systemd/system/v2ray_iptable.service

# remove v2ray
systemctl stop v2ray.service
systemctl disable v2ray.service
rm /etc/systemd/system/v2ray.service

rm /usr/local/bin/v2ray
rm /usr/local/bin/v2ctl
rm -rf /etc/v2ray/
rm -rf /var/log/v2ray/
rm -rf /usr/local/share/v2ray/

#
systemctl daemon-reload
systemctl reset-failed

#
echo "remove success, please reboot device!"