## 简介

将树莓派配置为 V2Ray 透明代理旁路由，只需要主路由设置好网关，即可代理主路由器下所有设备透明科学上网，接入网络的终端不需要做任何设置，只需要连入主路由WiFi或有线即可。支持直连\智能分流\全局代理 三种模式，并能自动管理订阅和各种高级策略设置，原理参考 [透明代理(TPROXY)
](https://guide.v2fly.org/app/tproxy.html)，TG讨论组:[https://t.me/v2raypi](https://t.me/v2raypi)

![1.png](pic/1.png)  

![2.png](pic/2.png)  

![3.png](pic/3.png)  

![4.png](pic/4.png)  

![5.png](pic/5.png)  

## 系统支持
MacOS  
Debian  
Armbian  
Raspberry Pi OS  
Ubuntu  
CentOS  
Docker  

## 硬件支持
MacBook 及其他所有能运行MacOS的硬件  
[Raspberry Pi 4B](https://www.raspberrypi.com/products/raspberry-pi-4-model-b)  
[ZeroPi](https://wiki.friendlyelec.com/wiki/index.php/ZeroPi)  
[NanoPi NEO 2](https://wiki.friendlyelec.com/wiki/index.php/NanoPi_NEO2)  
[NanoPi NEO 3](https://wiki.friendlyelec.com/wiki/index.php/NanoPi_NEO3)  
[Orange Pi Zero2](http://www.orangepi.cn/Orange%20Pi%20Zero2/index_cn.html)  
其他任何ARM、x86、x64 PC主机/软路由/电视盒子/开发板/虚拟机/Docker镜像  

![zeropi_1.jpg](pic/zeropi_1.jpg)  

![zeropi_2.jpg](pic/zeropi_2.jpg)  

## 安装方式
### Mac，不支持透明代理
```
# 安装 brew
ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"

# clone 代码
cd ~/Documents/
git clone https://github.com/twotreesus/V2RayPi.git
cd V2RayPi

# 安装依赖
./script/install_osx.sh

# 运行
python3 app.py

```
浏览器输入127.0.0.1:1086，即可访问面板  
浏览器设置 socks5 代理 127.0.0.1:1080，即可使用，Chrome 浏览器推荐使用 SwitchyOmega

### Debian / Armbian / Ubuntu / CentOS，支持旁路由透明代理
```
sudo su - root
cd /usr/local
git clone https://github.com/twotreesus/V2RayPi.git
cd V2RayPi/script
./install.sh #如果是 CentOS 请执行  ./install_centos.sh
```

重启服务
```
sudo supervisorctl restart v2raypi
```

设置树莓派为旁路由，树莓派修改为静态地址192.168.66.200，这里主路由是192.168.66.1
```
sudo nano /etc/dhcpcd.conf

# Example static IP configuration:
interface eth0
static ip_address=192.168.66.200/24
static routers=192.168.66.1
static domain_name_servers=192.168.66.1
```

重启树莓派
```
sudo reboot
```

然后主路由设置的DHCP网关为 192.168.66.200，这里以梅林为例，其他系统类似
![router.png](pic/router.png)

配置完成，浏览器输入192.168.66.200:1086，即可访问面板

### Docker，不支持透明代理
Docker镜像目前支持amd64和arm64平台，感谢[raydoom](https://github.com/raydoom)提供支持，镜像已上传到dockerhub，可直接拉取使用，如需要也可以用根目录下的Dockerfile自行编译镜像

```
docker run -d --restart=unless-stopped --name=v2ray-funpi -p 1080:1080 -p 1086:1086 raydoom/v2ray-funpi
```

浏览器输入DOCKER_HOST_IP:1086，即可访问面板  
其中，DOCKER_HOST_IP为docker主机ip地址  
浏览器设置 socks5 代理 DOCKER_HOST_IP:1080，即可使用，Chrome 浏览器推荐使用 SwitchyOmega  

## 修改启动配置
修改配置文件，以设置面板用户名、密码，端口，其他设置均可在面板内完成，ps：配置文件内不支持注释

```
sudo nano /usr/local/V2RayPi/config/app_config.json

{
    "py/object": "core.app_config.AppConfig",
    "user": "admin",
    "password": "admin",
    "port": 1086,
    "proxy_mode": 1,
    "inited": true
}
```

修改完成后重启服务即可
```
sudo supervisorctl restart v2raypi
```

## 系统更新
因为目前是源码方式运行，暂不提供按特定版本更新的特性，需要手动登录后台ssh来更新，参考一下步骤（具体更新内容见TG群）：

```
sudo git pull
sudo pip3 install -r script/requirements.txt
sudo supervisorctl restart v2raypi
```

## 卸载方式

```
sudo ./script/remove.sh
sudo reboot

```
