## 目录

- [简介](#简介)
  - [主要特性](#主要特性)
- [平台支持](#平台支持)
  - [操作系统](#操作系统)
  - [硬件平台](#硬件平台)
- [安装指南](#安装指南)
  - [Linux 安装](#linux-安装)
  - [MacOS 安装](#macos-安装)

- [系统维护](#系统维护)
  - [卸载](#卸载)
  - [故障排除](#故障排除)

## 简介

V2RayPi 是一个基于 V2Ray 的透明代理系统，专为树莓派和其他单板计算机设计。它可以将设备配置为旁路由，实现整个网络的智能代理。

### 主要特性
- **透明代理**：终端设备无需任何设置，只需连接到主路由即可
- **多种代理模式**：支持直连、智能分流、全局代理
- **自动化管理**：自动处理订阅更新和策略配置
- **一键更新**：内置系统更新功能，轻松保持系统最新
- **跨平台支持**：支持多种硬件平台和操作系统
- **简单易用**：图形化管理界面，操作直观

原理参考：[透明代理(TPROXY)](https://guide.v2fly.org/app/tproxy.html)

TG讨论组：[https://t.me/v2raypi](https://t.me/v2raypi)

## 平台支持

### 操作系统
- MacOS
- Debian
- Armbian
- Raspberry Pi OS
- Ubuntu

### 硬件平台
- [Raspberry Pi 4B](https://www.raspberrypi.com/products/raspberry-pi-4-model-b)
- [ZeroPi](https://wiki.friendlyelec.com/wiki/index.php/ZeroPi)
- [NanoPi NEO 2](https://wiki.friendlyelec.com/wiki/index.php/NanoPi_NEO2)
- [NanoPi NEO 3](https://wiki.friendlyelec.com/wiki/index.php/NanoPi_NEO3)
- [Orange Pi Zero2](http://www.orangepi.cn/Orange%20Pi%20Zero2/index_cn.html)
- MacBook 及其他 MacOS 设备
- 其他 ARM、x86、x64 设备（PC/软路由/电视盒子/开发板/虚拟机）

## 安装指南

### Linux 安装（支持透明代理）
支持的发行版：Debian / Armbian / Ubuntu / CentOS

```bash
# 1. 安装系统
sudo su - root
cd /usr/local
git clone https://github.com/twotreesus/V2RayPi.git
cd V2RayPi/script
./install.sh

# 2. 启动服务
sudo supervisorctl restart v2raypi

# 3. 配置静态 IP（以 192.168.66.0/24 网段为例）
sudo nano /etc/dhcpcd.conf

interface eth0
static ip_address=192.168.66.200/24
static routers=192.168.66.1
static domain_name_servers=192.168.66.1

# 4. 重启设备
sudo reboot
```

配置主路由：
1. 进入主路由器的 DHCP 设置
2. 将默认网关设置为 V2RayPi 的 IP 地址（如上述配置中的 192.168.66.200）

完成配置后，浏览器输入 V2RayPi 的地址（如 `192.168.66.200:1086`）即可访问管理面板

### MacOS 安装
> 注意：MacOS 版本不支持透明代理功能

```bash
# 1. 安装 Homebrew
ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

# 2. 克隆项目
cd ~/Documents/
git clone https://github.com/twotreesus/V2RayPi.git
cd V2RayPi

# 3. 安装依赖
./script/install_osx.sh

# 4. 启动服务
python3 app.py
```

安装完成后：
1. 访问管理面板：浏览器输入 `127.0.0.1:1086`
2. 配置代理：浏览器设置 SOCKS5 代理为 `127.0.0.1:1080`（Chrome 浏览器推荐使用 SwitchyOmega 插件）

### 系统更新
系统页面提供了一键更新功能，可以方便地将系统更新到最新版本：
1. 在系统页面可以看到最近的更新记录
2. 点击“检查更新”按钮检查是否有新版本
3. 如果有新版本，点击“更新并重启”按钮进行更新
4. 更新完成后，服务会自动重启

注意：更新过程中只会重启 V2RayPi 管理服务，不会影响 v2ray-core 的运行，因此代理服务不会中断

手动更新方式（可选）：
```bash
# 进入项目目录
cd V2RayPi

# 拉取最新代码
git pull

# 重启服务
sudo systemctl restart v2raypi
```



## 卸载方式

```
sudo ./script/remove.sh
sudo reboot
```

## 故障排除

### 维护操作
```bash
# 检查 V2RayPi 服务状态
sudo supervisorctl status v2raypi

# 查看 V2RayPi 服务日志
sudo supervisorctl tail -f v2raypi

# 重启 V2RayPi 服务
sudo supervisorctl restart v2raypi

# 查看 v2ray-core 日志
tail -f /var/log/v2ray/error.log
```

### 常见问题

1. 网络无法访问
   - 检查主路由的网关是否设置为 V2RayPi 的 IP
   - 检查 V2RayPi 的网络设置是否正确（IP、网关、DNS）， 应该设置为主路由
   - 检查订阅节点是否可用（速度测试）

2. 管理面板无法访问
   - 检查 V2RayPi 服务是否运行
   - 重启服务
   - 查看日志定位问题

3. 节点更新失败
   - 检查订阅地址是否可访问
   - 检查订阅格式是否正确（支持 v2ray 标准订阅格式）
   - 尝试手动添加节点

4. 系统更新失败
   - 检查网络连接
   - 检查 git 仓库状态：`git status`
   - 手动更新：`git reset --hard && git pull && sudo supervisorctl restart v2raypi`

5. 透明代理不生效
   - 确认系统是否支持 TPROXY（MacOS 不支持）
   - 检查 iptables 规则：`sudo iptables -t mangle -L`
   - 重启服务并检查日志

### 其他问题
如果遇到其他问题，可以：
1. 查看详细日志定位问题
2. 在 [GitHub Issues](https://github.com/twotreesus/V2RayPi/issues) 中搜索或提交问题
3. 加入 [TG 讨论组](https://t.me/v2raypi) 寻求帮助