# 全面转向 mihomo 内核

## Context

V2RayPi 目前是「三核心 + SOCKS 串联」架构：Xray 负责 TPROXY 入站、分流、DNS 和 vmess/vless/ss 出站；sing-box 作为 sidecar 提供 anytls/hysteria2（本地 SOCKS 2334）；mieru 作为第二个 sidecar（本地 SOCKS 2335）。这带来三处结构性负担：

1. **旁挂协议多一跳本机往返**：TPROXY → Xray dokodemo → Xray socks outbound → 127.0.0.1 → sidecar → 上游，UDP 还要依赖 sidecar 的 SOCKS5 UDP associate。
2. **`Node` 是所有协议字段的并集**（38 个字段），加一个协议要改 5 处；Clash 订阅经历 YAML → 扁平 Node → 重建 Xray JSON 的有损往返。
3. **mieru 的防回环靠工程手段兜住**：专用系统用户 + `runuser` + iptables `--uid-owner` bypass + SIGKILL 等待。

mihomo 原生支持 vmess / vless(reality) / ss / trojan / **anytls** / **mieru** / hysteria2 / tuic / wireguard 等全部协议，且原生支持 TProxy 入站。转向单核心后两个 sidecar 连同它们的进程管理、专用用户、iptables 绕行全部消失。

**目标**：用 mihomo 替换 Xray + sing-box + mieru，保留全部用户可见功能，UI 基本不变，订阅只支持 Clash YAML。

### 已确定的决策

| 决策点 | 选择 |
|---|---|
| 透明代理入口 | **TPROXY**，复用改造后的 `config_iptable.sh`（不用 TUN） |
| mihomo 配置内容 | **仅当前节点**，切换节点 = 重写 config + restart |
| 手动添加节点 | 支持 7 类协议分享 URL；「拷贝链接」输出协议 URL |
| 内部命名 | **全面重命名**（`v2ray_*` → `mihomo_*`，含 systemd 单元与 config 文件名） |
| 旧配置迁移 | **不做**，README 说明需重新添加订阅 |

### 明确的行为变更（需在 README 记录）

- BitTorrent 直连规则消失（mihomo 无协议嗅探类规则），BT 流量将按普通规则分流。
- 自定义路由规则不再支持 `ext:file:tag` 写法（mihomo 无此机制），需改用 `geosite:`。其余前缀（`domain:` / `full:` / `regexp:` / `geosite:`）与裸字符串语义保持不变。
- 节点分享使用协议 URL，支持复制链接与显示二维码；订阅级二维码保留。
- 日志由「访问日志 + 错误日志」两栏合并为单栏（mihomo 只有一个日志流）。
- 升级到本分支后需重新添加订阅（旧 `config/*.json` 不迁移）。

---

## 实施状态

代码已在分支 `feat/mihomo` 上完成，阶段 1–5 全部落地。相对 `dev` 共变更 42 个文件，新增 4647 行、删除 5326 行，净减少 679 行。

### 最终验收结论

验收表共 60 项，已通过 55 项，无失败或阻塞项。迁移的核心目标已经达到，可以进入合并前收尾：

- macOS 安装、Homebrew 服务、首次 GEO 数据下载、版本识别、日志读取与本地 SOCKS 代理全部通过。
- mihomo 配置预检、节点应用与切换、旧节点保护、三种代理模式、代理/直连优先、DNS 与 GEO 分流全部通过。
- 订阅增删改、收藏、协议 URL 分享与导入、二维码、自定义规则、广告拦截、Mux、日志级别与自动切换全部通过。
- 系统维护、会话、实时日志、mihomo/V2RayPi 更新、配置导入导出、重启与关机全部通过。
- Linux SBC 的安装保护、TPROXY TCP/UDP、DNS 劫持、routing-mark 防回环、旧链清理、重启恢复、资源占用与彻底卸载全部通过。
- 当前单元测试为 98 个，全部通过；7 类协议生成配置均通过真实 mihomo v1.19.29 校验。

### 尚未完成的验收

以下 5 项仍为待验收，不影响架构迁移结论，但应在发布前完成：

1. VMess 节点端到端访问。
2. VLESS Reality 节点端到端访问。
3. Shadowsocks 节点端到端访问。
4. Trojan 节点端到端访问。
5. 中英双语切换、页面重载与浏览器持久化。

Hysteria2、AnyTLS 与 Mieru 已完成真实节点验收。

### 验收期间确认并修复的问题

1. 安装阶段预置 `geoip.dat` / `geosite.dat`，显示下载进度，并在双文件下载成功后原子替换。
2. 修正 macOS Homebrew 日志路径和无 `v` 前缀的版本输出。
3. 屏蔽状态与性能轮询接口的访问日志，避免终端刷屏。
4. 修正全局代理仍受“代理优先”影响的问题；全局模式现在始终以 `MATCH,PROXY` 兜底。
5. 测试 SBC 证实 SIGHUP 不会应用新配置，节点切换改为固定重启 mihomo。
6. 移除意义有限的节点 Ping 功能；自动故障切换改为随机选择另一个节点。
7. 节点分享改为 7 类协议 URL，支持复制、二维码和手动导入收藏。
8. 优化高级设置与节点列表交互：默认策略改为双选项，点击节点行应用，收藏取消使用星标语义。
9. 前端增加中英双语，首次访问跟随浏览器语言，并在顶栏提供持久化切换。

### 实施中偏离计划的三处

1. **`test_config` 的 `-d` 目录**：原设计用临时目录，但 `mihomo -t` 会往 `-d` 下载 geoip/geosite，等于每次应用节点重下 ~27MB。改为 `-d` 指向真实配置目录、`-f` 指向临时候选文件；实测 0.38s 且不触碰运行中的 `config.yaml`。已加单元测试锁定这个行为。
2. **旧节点丢弃**：旧 `nodes.json` 能反序列化出 `clash={}` 的节点，在 UI 里看着可用但应用必然失败。新增 `NodeManager._drop_nodes_without_clash_payload()` 在加载时丢弃并记日志；`CoreService.load()` 同样重置无 payload 的当前节点。订阅地址保留，升级后点一次「全部更新」即可，比原计划的「重新添加订阅」轻。
3. **`remove.sh` 保留旧版本残留清理**：计划写的是删除 xray/sing-box/mieru 的全部卸载分支，但现存设备全是旧版本，不清理就等于「彻底卸载」留一堆垃圾。保留了一段明确标注为「旧版本遗留」的清理逻辑（含 `mieru` 系统用户）。

---

## 阶段划分

每个阶段结束都有明确的真机验证点，未通过不进入下一阶段。

### 阶段 0：分支与设备侧事实确认

新建分支 `feat/mihomo`（从 `dev` 切出）。

在测试 SBC 上手工确认以下事项（这些决定了后续代码怎么写，必须先落地）：

```bash
# 1. mihomo 是否支持 -t 配置校验（决定 apply 前能否预检）
mihomo -h
mihomo -t -d /etc/mihomo -f /etc/mihomo/config.yaml

# 2. SIGHUP 不会重新加载配置，切换节点固定使用 restart

# 3. 稳定版 release 无 checksums.txt，确认 GitHub API 是否返回 asset digest
curl -s https://api.github.com/repos/MetaCubeX/mihomo/releases/latest \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print([(a['name'],a.get('digest')) for a in d['assets'] if 'linux-arm64' in a['name']])"

# 4. 53 端口是否被系统服务占用（决定 dns.listen 用 1053 还是 53）
ss -lunp | grep ':53 '
systemctl is-active systemd-resolved

# 5. 规则语法与国家码大小写（手写一份最小 config.yaml 逐条试）
#    GEOIP,CN  vs  GEOIP,cn
#    NOT,((GEOIP,CN)),PROXY  的括号/逗号写法
#    nameserver-policy 的键是否接受逗号分隔多域名
mihomo -t -d /tmp/mihomo-test -f /tmp/mihomo-test/config.yaml
```

同时记录基线：`mihomo -d /etc/mihomo` 单跑时的 RSS 峰值与 geodata 加载耗时（`geodata-loader: memconservative`）。

> 第 1、3、5 项已在开发机上用真实二进制确认完毕，见上文「实施状态」。设备上只需复核第 2、4 项与 RSS 基线。

### 阶段 1：安装层与内核落地

先让 mihomo 在设备上被正确安装、启动、日志可读，暂不接 Web 层。

**新增 `script/update_mihomo.sh`** — 按 `script/update_mieru.sh` 的既有结构复刻（`fetch()` 用 curl/wget 回退、python3 解析 release JSON、原子安装 `.tmp.$$` + `mv -f`、`sudo` 仅在目标目录不可写时使用），差异：

- 资源命名 `mihomo-{platform}-{version}.gz`（单个 gzip 二进制，非 tar）；arch 映射沿用 `update_mieru.sh:39-50` 的 `OS:ARCH` case 结构，值改为 mihomo 的：`linux-amd64` / `linux-arm64` / `linux-armv7` / `linux-riscv64` / `darwin-amd64` / `darwin-arm64`
- 校验：稳定版无 `checksums.txt`，改用 GitHub API 的 asset `digest` 字段；若该字段不存在则退化为「gunzip 成功 + 新二进制 `-v` 能报版本」双重检查，并 `log()` 明确提示未做校验
- 接口保持一致：`bash script/update_mihomo.sh [install|update|version]`，成功打印 `[mihomo] installed $TAG at $DESTINATION`

**改写 `script/install.sh`**：

- 删除：sing-box 安装（`curl -fsSL https://sing-box.app/install.sh | sh`）、mieru 安装、**mieru 系统用户创建整段**（`useradd --system` / `MIERU_HOME` / `pkill`）、xray 安装与 `/usr/local/etc/xray` `/var/log/xray` 目录
- 新增：`bash "$SCRIPT_DIR/update_mihomo.sh" install`；`mkdir -p /etc/mihomo /var/log/mihomo`
- `/etc/rc.local` 中创建的目录由 `/var/log/xray` 改为 `/var/log/mihomo`
- 新写 `/etc/systemd/system/mihomo.service`（官方推荐 unit + 落地日志文件，保留现有 tail 式日志读取）：

```ini
[Unit]
Description=mihomo Daemon
After=network.target nss-lookup.target

[Service]
Type=simple
ExecStartPre=/usr/bin/sleep 1s
ExecStart=/usr/local/bin/mihomo -d /etc/mihomo
Restart=always
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE
StandardOutput=append:/var/log/mihomo/mihomo.log
StandardError=append:/var/log/mihomo/mihomo.log

[Install]
WantedBy=multi-user.target
```

- `xray_iptable.service` → `mihomo_iptable.service`（`Before=mihomo.service`）
- `systemctl enable mihomo.service`；**首次安装仍不启用 iptables 规则**（保留现有「首个节点应用成功后才启用」的保护语义）

**改写 `script/install_osx.sh`**：`brew install mihomo`（homebrew-core 已有该 formula，当前 1.19.29），删除 xray / sing-box / mieru 三处安装。

**改写 `script/remove.sh`**：删除 xray / sing-box / mieru 的全部卸载分支，**包括 `userdel -r mieru` 与 `MIERU_HOME` 清理**；改为清理 `mihomo` 二进制、`/etc/mihomo`、`/var/log/mihomo`、`mihomo.service`、`mihomo_iptable.service`。

**删除**：`script/update_xray.sh`、`script/update_v2ray.sh`、`script/update_mieru.sh`、`script/docker/v2ray.ini`、`script/docker/xray.ini`。

**改写 `script/config_iptable.sh`** — 见下方「iptables 变更」小节。

**阶段 1 验证**：设备上 `./script/install.sh` 全新安装成功；`mihomo -v` 有版本；手写一份最小 `config.yaml` 后 `systemctl start mihomo` 成功；`tail -f /var/log/mihomo/mihomo.log` 有输出；`systemctl is-enabled mihomo_iptable.service` 为 disabled。

### 阶段 2：配置生成与内核控制

**新增 `core/mihomo_default_path.py`**（替换 `core/v2ray_default_path.py`）：

- `config_dir()`：Linux `/etc/mihomo/`；macOS arm64 `/opt/homebrew/etc/mihomo/`，否则 `/usr/local/etc/mihomo/`
- `config_file()`：`<config_dir>/config.yaml`
- `log_file()`：Linux `/var/log/mihomo/mihomo.log`；macOS `~/Library/Logs/mihomo/mihomo.log`
- `asset_path()`：等于 `config_dir()`（mihomo 从 `-d` 目录读 `geoip.dat` / `geosite.dat`）

**新增 `core/mihomo_config.py`**（替换 854 行的 `core/v2ray_config.py`，预计约 380 行）。核心简化：直接构造 `dict` 后 `yaml.safe_dump(sort_keys=False, allow_unicode=True)`，**不再需要** `DontPickleNone`、jsonpickle handler 注册、以及 `Protocol*` / `StreamSettings` / `Inbound` / `Outbound` 整片嵌套类树（`v2ray_config.py:16-320`）。

```
MihomoConfig.gen_config(user_config, all_nodes, subscribe_hosts) -> str
  _gen_general(user_config)      # mode / log-level / mixed-port / listeners
                                 # / routing-mark / geodata-* / sniffer
  _gen_proxies(user_config)      # 仅当前节点，原样透传 node.clash + 可选 smux 注入
  _gen_dns(user_config, ...)     # 见「DNS 设计」
  _gen_rules(user_config, ...)   # 见「规则映射」
  translate_domain_pattern(s)    # 用户自定义域名规则 → mihomo 规则类型 + payload
  translate_ip_pattern(s)        # 单 IP / CIDR / geoip → IP-CIDR（带 no-resolve）/ GEOIP
```

常量：`PROXY_TAG = 'PROXY'`、`TPROXY_PORT = 12345`（沿用旧端口，见 iptables 小节）、`DNS_PORT = 1053`、`ROUTING_MARK = 255`。geodata 固定 `geodata-mode: true`（复用 V2Ray 格式的 `geoip.dat` / `geosite.dat`，与现有 GEO 更新功能同源）+ `geodata-loader: memconservative`（小内存 SBC）。Mux 开关映射为对当前 proxy dict 注入 `smux: {enabled: bool}`，**仅对 vmess/vless/trojan/ss 这类流式协议注入**（hysteria2/tuic/anytls/mieru 跳过，否则 mihomo 报错）。

**新增 `core/mihomo_controller.py`**（替换 `core/v2ray_controller.py`，删掉对两个 sidecar 的全部委托方法）：

- `start/stop/restart`：Linux `systemctl <action> mihomo.service`；macOS `brew services <action> mihomo`
- `running()`：`pgrep -x mihomo`
- `version()`：`mihomo -v`
- `check_new_version()`：GitHub API `MetaCubeX/mihomo/releases/latest`
- `update()`：`bash ./script/update_mihomo.sh update`
- `apply_node()`：生成 YAML → `test_config()` 预检 → 写入 → `restart()`
- `test_config()`：`mihomo -t -d <dir> -f <file>`（阶段 0 确认可用性；不可用则该方法直接返回 True 并记日志）
- `enable_iptables()`：**沿用现有状态机**（`v2ray_controller.py:126-146` 的 `is-enabled` / `is-active` 三态判断），只把服务名换成 `mihomo_iptable.service`
- `check_new_geo_data()` / `update_geo_data()`：逻辑不变，落盘目标改为 `MihomoDefaultPath.asset_path()` 下的 `geoip.dat` / `geosite.dat`
- `log()`：tail `MihomoDefaultPath.log_file()`
- `MacOSMihomoController` 子类保留（`enable_iptables()` 空实现）

**新增 `core/mihomo_user_config.py`**（替换 `core/v2ray_user_config.py`）：类名 `MihomoUserConfig`，`filename()` → `config/mihomo_user_config.json`。结构与选项**全部保留**（ProxyMode 三态、Log、InBound、Policy、DnsConfig、AutoDetectAndSwitch、GeoData、proxy_preferred、enable_mux、block_ad）。仅 `Log.level` 在生成时映射到 mihomo 取值（`none` → `silent`，其余同名）。

**删除**：`core/v2ray_config.py`、`core/v2ray_controller.py`、`core/v2ray_user_config.py`、`core/v2ray_default_path.py`、`core/singbox_controller.py`、`core/mieru_controller.py`。

**阶段 2 验证**：`python3 -c` 直接调用 `MihomoConfig.gen_config` 打印 YAML，肉眼比对三种代理模式下的规则顺序；`mihomo -t` 校验通过；设备上手工 `apply` 一个真实节点后能上网。

### 阶段 3：节点模型与订阅（只留 Clash）

**改写 `core/node.py`**（408 行 → 约 60 行）。`Node` 保存订阅里的原始 proxy dict，另存少量归一化字段供 UI 使用：

```python
class Node(BaseDataItem):
    def __init__(self):
        self.clash = {}        # 原始 Clash proxy dict，无损透传给 mihomo
        self.ps = None         # = clash['name']
        self.add = None        # = clash['server']
        self.port = None       # = clash['port']
        self.protocol = None   # = clash['type']，供 UI 徽标使用

    @property
    def link(self) -> str:     # 输出对应协议的分享 URL
        return encode_node_uri(self.clash)
```

`ps` / `add` / `port` / `protocol` 字段名保持不变——`CoreService.status()` 会把 `node.dump()` 合并进响应，模板直接读这些键。

协议 URL 的编解码集中到 `core/node_uri.py`，支持 VMess、VLESS、Shadowsocks、Trojan、Hysteria2、AnyTLS 与 Mieru。

**改写 `core/node_manager.py`**：

- `update_group()`：只走 Clash YAML 分支，删除 base64 解码分支与 `_parse_node_uri()`（`node_manager.py:38-61`）。非 Clash 内容（`yaml.safe_load` 失败或缺 `proxies` 键）视为失败并记日志
- `_clash_proxy_to_node()`（90 行的逐协议字段搬运，`node_manager.py:63-151`）→ `_proxy_to_node()`（约 25 行）：按**支持类型白名单**过滤，通过则原样存 dict
  - 白名单常量放在 `mihomo_config.py` 里与 smux 白名单并列，便于一处维护
  - 白名单外的类型跳过并计数，`update_group` 结束后 log 一行「跳过 N 个不支持的节点」——这是「仅载入当前节点」下防止单个坏节点污染配置的第一道闸
- `add_manual_node()` 解析单节点分享 URL 并保存到收藏
- 删除节点 Ping 与延迟显示；保留 `favorite_node` / `find_node` / `delete_node` / `all_nodes` / `subscribe_hosts` / `refresh_update_time`

**改写 `core/core_service.py`**（结构不变，只做重命名与删除）：

- `cls.v2ray` → `cls.mihomo`；`stop_v2ray()` → `stop_mihomo()`；`update_v2ray()` → `update_mihomo()`
- 删除 `update_singbox()`、`update_mieru()` 与旧的 `CoreService.add_manual_node()` 包装
- `status()` 删除 `singbox_version` / `mieru_version` / `mieru_running` 三个键
- **保留不动**：session 管理、git 自更新与分支切换、`auto_detect_job`（含 `restart_auto_detect` / `auto_detect_start` / `auto_detect_cancel`）、`traffic_monitor` 采样调度、`export_config` / `import_config`、`make_policy`

**`core/keys.py`**：删除 8 个 `*_scheme` 常量（`vmess_scheme` … `mierus_scheme`），其余不动。

**阶段 3 验证**：设备上添加一个真实 Clash 订阅 → 节点列表正确显示各协议徽标 → 逐个应用 vmess / vless(reality) / hysteria2 / anytls / mieru 节点各自能上网（这一步是替掉两个 sidecar 的核心证明）。

### 阶段 4：Web 层与 UI

**`app.py`**：

- `/check_v2ray_new_ver` → `/check_mihomo_new_ver`；`/update_v2ray` → `/update_mihomo`
- **删除路由**：`/check_singbox_new_ver`、`/update_singbox`、`/check_mieru_new_ver`、`/update_mieru`；`/add_manual_node` 改为 POST 分享 URL
- `/stream_logs`（`app.py:379-438`）：日志源由 access + error 两个文件合并为 `MihomoDefaultPath.log_file()` 单文件，SSE 事件名 `access` / `xray_error` 合并为单个 `mihomo`
- 其余路由签名与返回结构**保持不变**（`/get_status`、`/get_performance`、`/subscribe_list`、`/apply_node`、`/get_node_link`、`/switch_proxy_mode`、`/get_advance_config`、`/set_advance_config`、`/make_policy`、geo 相关、系统维护相关、鉴权相关）
  - 迁移完成后 `/get_performance` 增加了 `history` 字段（后端维护最近 60 秒的 CPU、内存与上下行序列，供状态页图表使用），原有 `cpu` / `memory` / `network` 三个当前值字段不变

**`templates/system.html`**：删除 sing-box 卡片（50-91）与 Mieru 卡片（93-134）；Xray 卡片改为 mihomo，把不一致的 `v2ray_*` 命名一并对齐（`v2ray_current_ver` → `mihomo_current_ver`、`check_v2ray_new_ver()` → `check_mihomo_new_ver()`、`update_v2ray()` → `update_mihomo()`）；页内日志查看器（300-316 附近）两栏合一。

**`templates/subscribe.html`**：订阅仅支持 Clash YAML；节点分享改为协议 URL，支持复制与二维码；支持将单节点分享 URL 手动添加到收藏。

**`templates/status.html`**：`#v2ray_current_ver` 相关标签改为 mihomo。

**`templates/advance.html`**：日志级别说明文案（313-317）里的 "Xray" 改为 "mihomo"，选项值对齐 mihomo 取值；Mux 开关补一句「仅对 vmess/vless/trojan/ss 生效」；自定义路由规则的帮助文案说明支持的前缀写法。

**`templates/index.html`**：`hs_protocol_badge()`（402-411）的协议名来源从自定义 `protocol` 变为 Clash `type`，需覆盖白名单里的全部类型（新增 trojan / tuic / wireguard 等），白名单外走通用样式。**注意** `protocol_badge()` 与 `.node-type-*` CSS 在 index / status / subscribe 三处各有一份拷贝，三处需同步改。

**`templates/log.html`**：该模板调用 `/get_access_log` 与 `/get_error_log`，这两个路由在 `app.py` 中已不存在（现有日志功能实际在 system.html 内），属死代码——一并删除。

**阶段 4 验证**：浏览器走完全流程——登录、状态页图表、切换三种代理模式、订阅增删改与更新、节点应用与收藏、分享 URL 复制与二维码、高级设置全部字段保存与重置、自定义规则增删、GEO 更新、mihomo 版本查询与升级、V2RayPi 分支切换与自更新、配置导出导入、重启/关机。

### 阶段 5：测试与文档

- **删除** `tests/test_mieru.py`（267 行，整个 mieru sidecar 的测试）
- **改写** `tests/test_tproxy.py`：`V2rayController` → `MihomoController`，服务名 `xray_iptable.service` → `mihomo_iptable.service`；`CoreServiceTproxyIntegrationTest` 里 `patch.multiple` 的 `v2ray` 键改为 `mihomo`
- **改写** `tests/test_traffic_monitor.py`：只需同步链名常量，其余测试逻辑不动
- **新增** `tests/test_mihomo_config.py`：三种代理模式下的规则顺序与内容、`proxy_preferred` / `block_ad` / `geo_data.enabled()` 各组合、DNS 块、listeners、节点 dict 原样透传、smux 按协议注入、`translate_domain_pattern` / `translate_ip_pattern` 的全部分支
- **新增** `tests/test_node_manager.py`：Clash YAML 解析、白名单外类型被跳过、非 Clash 内容被拒绝、`favorite_node` 去重

沿用现有 `unittest` 风格（无 pytest fixture、无 conftest.py），`python3 -m unittest discover tests` 可跑。

**README 全面改写**：协议支持表（单核心，去掉「核心组件」列的三分）、安装步骤（去 sing-box/mieru）、故障排除（`journalctl -u mihomo` / `mihomo -t` / `/var/log/mihomo/mihomo.log`）、以及上文「明确的行为变更」四条。

---

## 规则映射

`proxy_mode != Direct` 时按此顺序生成（左列为被替换的 `v2ray_config.py` 生成器）：

| 原 Xray 规则 | mihomo 规则 |
|---|---|
| `_make_dnsout_rule` | **无需规则** — DNS 由 `dns.listen` + iptables 重定向承担 |
| `_make_ntp_rule` | `AND,((NETWORK,udp),(DST-PORT,123)),DIRECT` |
| `_make_bt_rule` | **无对应实现**，见下方说明 |
| `_make_private_rule`（`geoip:private`） | 展开为显式 CIDR 列表（见下） |
| `_make_ip_local_dns_rule` | `IP-CIDR,<local_dns>/32,DIRECT,no-resolve` |
| `_make_ip_remote_dns_rule` | `IP-CIDR,<remote_dns>/32,PROXY,no-resolve` |
| `_make_adblock_rule` | `GEOSITE,category-ads-all,REJECT` |
| 节点/订阅域名直连 | `DOMAIN-SUFFIX,<host>,DIRECT`（每 host 一条） |
| 节点/订阅 IP 直连 | `IP-CIDR,<ip>/32,DIRECT,no-resolve` |
| 用户自定义策略 | 见「域名/IP 模式翻译」，顺序与 `policys` 一致 |
| `_make_ip_cn_rule` + `_make_site_cn_rule` | `GEOSITE,cn,DIRECT` 然后 `GEOIP,CN,DIRECT,no-resolve` |
| `_make_site_not_cn_rule` | `GEOSITE,geolocation-!cn,PROXY` |
| `_make_ip_not_cn_rule`（`geoip:!cn`） | **不再生成**，见下方「直连优先」说明 |
| 默认出站顺序 | `MATCH,PROXY`（`proxy_preferred`）或 `MATCH,DIRECT` |

私有地址显式展开，**不用** `GEOIP,private` 或 `GEOIP,LAN`——这条规则关系到 LAN 可达性与 SSH 救援，不应依赖 geo 文件是否就位或分类名是否存在：

```
IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
IP-CIDR,169.254.0.0/16,DIRECT,no-resolve
IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
IP-CIDR,224.0.0.0/4,DIRECT,no-resolve
IP-CIDR,255.255.255.255/32,DIRECT,no-resolve
IP-CIDR6,::1/128,DIRECT,no-resolve
IP-CIDR6,fc00::/7,DIRECT,no-resolve
IP-CIDR6,fe80::/10,DIRECT,no-resolve
```

三种模式的差异：

- **Direct(0)**：不生成 `proxies`，规则仅 `MATCH,DIRECT`
- **ProxyAuto(1)**：全部规则，含 `GEOSITE,cn` / `GEOIP,CN`；`GEOSITE,geolocation-!cn,PROXY` 仅在 `not proxy_preferred` 时追加
- **ProxyGlobal(2)**：跳过上面两组 cn 规则，其余相同

**有意的顺序调整**：Xray 里 `geoip:cn` 排在 `geosite:cn` 之前（`v2ray_config.py:488`）；mihomo 中 GEOIP 规则遇到域名会触发 DNS 解析，因此把 `GEOSITE,cn` 提到 `GEOIP,CN` 之前，避免无谓解析。

**「直连优先」是名单模式，不再翻译 `geoip:!cn`。** Xray 版本在 `not proxy_preferred` 下同时下发 `geosite:geolocation-!cn → proxy` 与 `geoip:!cn → proxy`，而路由用的是 `domainStrategy: IPOnDemand`，域名也会被解析后按 IP 匹配。直译成 `NOT,((GEOIP,CN)),PROXY` 后同样如此：名单外的海外域名会在这一条被解析、判定为非中国 IP、然后走代理，`MATCH,DIRECT` 只剩「不在 `geosite:cn` 名单里、却解析到中国 IP」这一种情况可达。两个选项因此几乎没有区别，与界面上「已识别的海外网站走代理，其他网站默认直接连接，更节省代理流量」的描述不符。

现在 `not proxy_preferred` 只追加 `GEOSITE,geolocation-!cn,PROXY`：名单内的海外站点走代理，其余（含裸 IP 的海外目标）落到 `MATCH,DIRECT`。这样内置规则里所有目的地 IP 类规则就都带 `no-resolve` 了（用户自己写的 geo 规则仍按解析后的 IP 匹配，原因见下方翻译表）。门控 `geo_data.enabled()` 一并去掉——它只表示用户是否在界面上更新过第三方 GEO 数据库，而 `geosite.dat` 缺失时 mihomo 会自行下载；保留门控只会让没点过更新的用户在该模式下变成全直连。

**无对应实现：BitTorrent 直连。** mihomo 没有协议嗅探类规则，`protocol: bittorrent → direct` 无法忠实翻译。不做近似（按端口段猜测会误伤正常流量），直接移除并在 README 记录。用户如需 BT 直连，可通过自定义路由规则针对 tracker 域名配置。

### 域名/IP 模式翻译

用户在「自定义路由规则」里输入自由文本，历史上接受 Xray 的前缀写法。翻译函数：

| 输入 | 输出 | 说明 |
|---|---|---|
| `geosite:foo` | `GEOSITE,foo` | |
| `full:foo.com` | `DOMAIN,foo.com` | |
| `domain:foo.com` | `DOMAIN-SUFFIX,foo.com` | |
| `regexp:^ad.*` | `DOMAIN-REGEX,^ad.*` | |
| `keyword:foo` | `DOMAIN-KEYWORD,foo` | 新增别名，Xray 无此前缀 |
| 裸字符串 `foo.com` | `DOMAIN-KEYWORD,foo.com` | 见下 |
| `ext:file:tag` | **拒绝**并返回明确错误 | mihomo 无此机制，提示改用 `geosite:` |

裸字符串映射为 **`DOMAIN-KEYWORD`（子串匹配），而非 `DOMAIN-SUFFIX`**。Xray 的无前缀域名本就是子串匹配——`sina.com` 会匹配 `sina.com.cn` 和 `www.sina.com`。映射成后缀匹配会静默收窄用户已有规则的匹配范围（`google` 就不再匹配 `googleapis.com`），属于无声的行为变更。忠实优先。advance.html 的帮助文案应写明「不带前缀 = 包含匹配」，并把 `domain:` 推荐为后缀匹配的写法。

IP 类策略：

| 输入 | 输出 |
|---|---|
| `1.2.3.4` | `IP-CIDR,1.2.3.4/32,no-resolve` |
| `1.2.3.0/24` | `IP-CIDR,1.2.3.0/24,no-resolve` |
| IPv6 单地址 / CIDR | `IP-CIDR6,...,no-resolve` |
| `geoip:cn` | `GEOIP,CN` |
| `geoip:!cn` | `NOT,((GEOIP,CN))` |
| `ext:...` | **拒绝**并返回明确错误 |

字面地址带 `no-resolve`：用户写的是具体地址，要匹配域名他会写域名规则，没必要为此对每条连接触发解析。

**geo 规则两种写法都不带 `no-resolve`。** geo 规则问的是「目的地在哪个国家」，不解析就无法对域名作答：正写法 `geoip:cn` 会对域名静默失效，负写法更糟——`no-resolve` 只能写进子规则 `NOT,((GEOIP,CN,no-resolve))`（追加在末尾会被 mihomo 当成目标出站而报 `proxy [no-resolve] not found`），而域名没有已知 IP 时子规则不匹配、`NOT` 取反后会匹配**所有域名**。因此两种写法统一按解析后的 IP 匹配，与 Xray 时代 `domainStrategy: IPOnDemand` 的行为一致。内置的 `GEOIP,CN,DIRECT,no-resolve` 是另一回事：它前面有 `GEOSITE,cn` 负责域名侧，无需再解析。

**需在真机确认**：`GEOIP` 的国家码大小写。Loyalsoldier 的 `geoip.dat` 分类名是小写（`cn`），而 Clash 系历来期望大写 ISO 码。用 `mihomo -t` 对 `GEOIP,CN` 与 `GEOIP,cn` 各测一次，以及 `NOT,((GEOIP,CN))` 的逗号/括号写法是否被当前版本接受。

## DNS 设计

选 **`redir-host`**，不用 fake-ip。理由：README 中「把主路由 DNS 指向 V2RayPi」是**可选**步骤；即使 iptables 拦下了 udp/53，走 DoH/DoT（443 端口）的客户端仍会完全绕过我们的 DNS。fake-ip 依赖「所有解析都经过 mihomo」这个前提，前提一破，mihomo 收到的就是一个从未映射过的真实 IP，反查失败后只能退回按 IP 分流——那正是 redir-host 直接给出的结果，却省掉了 fake-ip-range 耗尽、fake-ip-filter 维护和额外状态。fake-ip 可作为后续 advance_config 里的开关。

配套必须开启 **`sniffer`**，这是 Xray dokodemo-door 上 `sniffing: {enabled: true, destOverride: [http, tls], excludedDomain: "Mijia Cloud"}`（`v2ray_config.py:292-296`）的 1:1 替代——让绕过我们 DNS 的连接仍能通过 SNI / Host 恢复域名，域名类规则才不会失效：

```yaml
sniffer:
  enable: true
  sniff:
    HTTP: {ports: [80, 8080-8880], override-destination: true}
    TLS:  {ports: [443, 8443]}
    QUIC: {ports: [443, 8443]}
  skip-domain:
    - "Mijia Cloud"
```

`proxy_mode != Direct`：

```yaml
dns:
  enable: true
  listen: 0.0.0.0:1053
  ipv6: false                              # 对应现有 queryStrategy: UseIPv4
  enhanced-mode: redir-host
  use-hosts: true
  prefer-h3: false                         # respect-rules 与 prefer-h3 不可同时用
  respect-rules: true                      # 关键，见下
  default-nameserver: [<local_dns>]        # 解析 DNS 服务器自身域名，必须是 IP
  nameserver: [<remote_dns>]               # 默认远程，对应 Xray servers[0]
  proxy-server-nameserver: [<local_dns>]   # 节点服务器域名用本地 DNS 解析
  nameserver-policy:
    "+.ntp.org": [<local_dns>]
    "geosite:speedtest": [<local_dns>]
    "<每个节点域名>": [<local_dns>]
    "<每个订阅域名>": [<local_dns>]
    "geosite:cn": [<local_dns>]            # 仅 ProxyAuto
    "<用户 direct 类型的域名策略>": [<local_dns>]
```

**`respect-rules: true` 是必须的，不是可选。** Xray 的远程 DNS 之所以有意义，是因为 dns-out 发往 `8.8.8.8` 的查询包会再次过路由规则，被 `_make_ip_remote_dns_rule` 送进代理（`v2ray_config.py:456`、`821-827`）——明文 UDP 打到 8.8.8.8 在国内是必然被污染的。mihomo 默认 `respect-rules: false`，自身的 DNS 查询**不过 `rules:`**，会直连 8.8.8.8，等于把「远程 DNS」这个功能整体废掉。开 `respect-rules: true` 后，规则表里的 `IP-CIDR,<remote_dns>/32,PROXY,no-resolve` 才会生效。mihomo 要求开启该项时必须同时设置 `proxy-server-nameserver`（否则解析节点域名会自我死锁），上面已配。

其余与现有 Xray DNS 块（`v2ray_config.py:417-444`）逐项对应：Xray 的 `servers[0] = remote_dns` → `nameserver`；Xray `local_server.domains` 那一串 → `nameserver-policy`；`queryStrategy: UseIPv4` → `ipv6: false`。`proxy-server-nameserver` 是 mihomo 独有的改进——保证节点服务器域名一定用本地 DNS 解析，比 Xray 里靠 `domains` 列表覆盖更可靠。

`proxy_mode == Direct`：

```yaml
dns:
  enable: true
  listen: 0.0.0.0:1053
  ipv6: false
  enhanced-mode: redir-host
  respect-rules: false
  default-nameserver: [<local_dns>]
  nameserver: [<local_dns>]
```

**LAN 客户端的 DNS 如何到达 mihomo**：mangle PREROUTING 在 nat PREROUTING **之前**遍历，而 TPROXY 是终结性动作——一旦命中就本地投递，nat 表没有机会介入。因此必须在 MIHOMO 链里让 53 端口先 `RETURN`，再由 nat 表 `REDIRECT --to-ports 1053` 接走。这是本次改造中最高风险的一处，见下。

**需在真机确认**：`nameserver-policy` 的键在当前版本是否支持逗号分隔的多域名列表（新版支持，旧版要求一键一域名）。用 `mihomo -t` 验证；不支持就一域名一条目。

## iptables 变更

`script/config_iptable.sh` 的改动。链名 `V2RAY` → `MIHOMO`、`V2RAY_MASK` → `MIHOMO_MASK`；`V2RAYPI_TRAFFIC_UP/DOWN` **保持不变**（前缀是项目名而非内核名，项目名不改），因此 `core/traffic_monitor.py` 完全不用动。

1. **TPROXY 端口沿用 12345**，但参数化为 `TPROXY_PORT="${V2RAYPI_TPROXY_PORT:-12345}"`（照 `LAN_CIDR` 的现有写法），`mihomo_config.py` 里同名常量保持一致。沿用旧端口的额外好处：原地升级的设备上若残留旧 `V2RAY` 链，它 TPROXY 的目标端口仍有 mihomo 在监听，退化为「重复跳转」而非直接断网
2. **删除 mieru owner bypass 整段**（`config_iptable.sh:86-92`，含 `MIERU_USER` 变量与 `--uid-owner` 规则）。mihomo 是单核心，自身用 `routing-mark: 255` 打标，不再需要基于 uid 的绕行
3. 链名替换，连带 `delete_rule` / `ensure_chain` / PREROUTING 与 OUTPUT 的 jump 全部同步
4. MIHOMO 链在 TPROXY 之前插入 53 端口放行，把 DNS 让给 nat 表：

```bash
iptables -t mangle -A MIHOMO -p udp --dport 53 -j RETURN
iptables -t mangle -A MIHOMO -p tcp --dport 53 -j RETURN
```

5. 新增 nat 表 DNS 重定向：

```bash
ensure_chain nat MIHOMO_DNS
iptables -t nat -A MIHOMO_DNS -s "$LAN_CIDR" -p udp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A MIHOMO_DNS -s "$LAN_CIDR" -p tcp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A PREROUTING -j MIHOMO_DNS

# 网关本机的 DNS 也交给 mihomo，避免本机解析被污染。
# mihomo 自身出站带 routing-mark 255，先 RETURN 防回环。
ensure_chain nat MIHOMO_DNS_OUT
iptables -t nat -A MIHOMO_DNS_OUT -m mark --mark 0xff -j RETURN
iptables -t nat -A MIHOMO_DNS_OUT -p udp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A MIHOMO_DNS_OUT -p tcp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A OUTPUT -j MIHOMO_DNS_OUT
```

6. 两条链里的 `-m mark --mark 0xff -j RETURN` 防回环规则**保留不变**。Xray 原先靠出站 `sockopt.mark = 255`（`v2ray_config.py:319`）；mihomo 用顶层 `routing-mark: 255`，255 = 0xff，机制完全对齐，脚本这部分零改动
7. LAN 直连 RETURN 规则（`config_iptable.sh:71-72`、`84-85`）保留不变——这是 mihomo 挂掉时 SSH 仍可达的保命规则
8. 流量计数链与其 jump 全部保留不变

**必须新增的遗留清理**。iptables 链是内核常驻状态，不随代码更新消失。原地升级的设备上仍存在旧的 `V2RAY` / `V2RAY_MASK` 链和指向它们的 PREROUTING/OUTPUT jump，新脚本的 `delete_rule` 只针对 `MIHOMO`，不会清掉它们，结果是同一个包被两条链重复处理。新脚本必须无条件执行清理（不加「是否升级」的判断，保持现有幂等风格）：

```bash
cleanup_legacy_chains() {
    delete_rule mangle PREROUTING -j V2RAY
    delete_rule mangle OUTPUT -j V2RAY_MASK
    for chain in V2RAY V2RAY_MASK; do
        iptables -t mangle -F "$chain" 2>/dev/null || true
        iptables -t mangle -X "$chain" 2>/dev/null || true
    done
}
```

### SBC 真机结论

- `routing-mark: 255` 防回环验证通过，mihomo 自身连接与 DNS 查询未被 OUTPUT 链重复捕获。
- DNS 保持 1053 + nat 重定向，不与系统 53 端口服务抢占。
- LAN 客户端 UDP/TCP 53 查询能进入 mihomo，相关 iptables 计数器按预期增长。

---

## 验证方式

真机验证已按阶段 1→5 完成。最终回归结果：

**功能面**
1. 已通过：三种代理模式各自生效（直连 / 智能分流 / 全局代理）。
2. 已通过：Hysteria2、AnyTLS、Mieru 真实节点；待验收：VMess、VLESS Reality、Shadowsocks、Trojan 真实节点。
3. 已通过：订阅添加、更新单个、全部更新、删除、复制链接与二维码。
4. 已通过：节点点击行应用、收藏、取消收藏、删除、分享 URL、二维码与手动导入。
5. 已通过：自动切换、本地 SOCKS、DNS、自定义规则、GEO 更新、Mux、广告拦截和日志级别。
6. 已通过：mihomo/V2RayPi 更新、密码修改、配置导入导出、重启和关机。
7. 已通过：SSE 实时日志流。
8. 待验收：中英双语首次语言检测、顶栏切换、完整页面翻译与刷新后持久化。

**非功能面**
9. 已通过：512MB 目标设备资源占用可接受。
10. 已通过：设备重启后 mihomo 与 iptables 服务自动恢复。
11. 已通过：全新安装与彻底卸载无功能性残留。

**单元测试**
```bash
python3 -m unittest discover tests -v
```
