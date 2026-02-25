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
systemctl stop xray_iptable.service
systemctl disable xray_iptable.service
rm /etc/systemd/system/xray_iptable.service

# remove xray
systemctl stop xray.service
systemctl disable xray.service
rm -f /etc/systemd/system/xray.service
rm -f /etc/systemd/system/xray@.service
rm -rf /etc/systemd/system/xray.service.d
rm -rf /etc/systemd/system/xray@.service.d

rm -f /usr/local/bin/xray
rm -rf /usr/local/etc/xray/
rm -rf /var/log/xray/
rm -rf /usr/local/share/xray/

#
systemctl daemon-reload
systemctl reset-failed

#
echo "remove success, please reboot device!"