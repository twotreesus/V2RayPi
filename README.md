## 目录

- [简介](#简介)
  - [主要特性](#主要特性)
- [平台支持](#平台支持)
  - [操作系统](#操作系统)
  - [硬件平台](#硬件平台)
- [安装指南](#安装指南)
  - [Linux 安装](#linux-安装)
  - [管理员密码](#管理员密码)
  - [MacOS 安装](#macos-安装)

- [系统维护](#系统维护)
  - [卸载](#卸载)
  - [故障排除](#故障排除)

## 简介

V2RayPi 是一个基于 V2Ray 的透明代理系统，专为树莓派和其他单板计算机设计。它可以将设备配置为旁路由，实现整个网络的智能代理。

### 工作原理

V2RayPi 采用旁路由模式工作：
1. **网络拓扑**
   ```
                                    节点服务器
                                         ^
                                         |
   终端设备 -> 主路由(DHCP) <-> V2RayPi(TPROXY) <-> 互联网
   (WiFi/有线)     (网关重定向)   (智能分流)
   ```

2. **数据流向**
   - 终端设备连接到主路由的 WiFi 网络
   - 主路由通过 DHCP 设置，将终端设备的数据重定向到旁路由
   - 旁路由将终端数据通过 TPROXY 转发给 V2RayPi
   - V2RayPi 根据规则决定是直连还是代理，最终通过主路由访问网络出口

3. **网络设置**
   - 主路由：保持原有的上网配置，仅需设置 DHCP 网关为 V2RayPi 的 IP
   - V2RayPi：配置为与主路由同网段的静态 IP，网关指向主路由
   - 终端设备：无需任何设置，通过 DHCP 自动配置

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

# 3. 配置静态 IP 和网关，这里假设主路由 IP 是 192.168.66.1
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
3. 为防止 DNS 劫持，将 DNS 服务器设置为 V2RayPi 的 IP 地址

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

### 管理员密码
系统首次安装后，默认管理员密码为 `admin`。出于安全考虑，强烈建议在首次登录后立即修改密码：
1. 在管理面板中点击「系统维护」选项卡
2. 在「密码管理」区域输入新密码
3. 点击「更新」按钮完成修改

注意：密码修改后将立即生效，请妥善保管新密码。如果忘记密码，可以通过以下方式重置：
```bash
# 进入项目目录
cd /usr/local/V2RayPi

# 删除密码哈希，重置为默认密码 admin
python3 -c "import json; config = json.load(open('config/app_config.json')); config.pop('password_hash', None); json.dump(config, open('config/app_config.json', 'w'), indent=4)"

# 重启服务
sudo supervisorctl restart v2raypi
```

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

# 手动强制更新 V2RayPi 服务
sudo git reset --hard && sudo git pull && sudo supervisorctl restart v2raypi

# 查看 v2ray-core 日志
tail -f /var/log/v2ray/error.log
```

### 常见问题

1. 网络无法访问
   - 检查主路由的 DHCP 网关是否设置为 V2RayPi 的 IP
   - 检查 V2RayPi 旁路由的网络设置是否正确（IP、网关、DNS），自身为静态 IP，网关和 DNS 应该为主路由的 IP
   - 检查 v2ray-core 是否运行
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
   - 手动更新V2RayPi

5. 透明代理不生效
   - 确认系统是否支持 TPROXY（MacOS 不支持）
   - 检查 iptables 规则：`sudo iptables -t mangle -L`
   - 重启服务并检查日志

### 其他问题
如果遇到其他问题，可以：
1. 查看详细日志定位问题
2. 在 [GitHub Issues](https://github.com/twotreesus/V2RayPi/issues) 中搜索或提交问题
3. 加入 [TG 讨论组](https://t.me/v2raypi) 寻求帮助