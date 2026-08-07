#!/usr/bin/env bash

# This script is intentionally safe to run repeatedly.  It is called both by
# the first successful node application and by xray_iptable.service at boot.
set -u

# Delete every occurrence of a jump rule.  This avoids duplicate jumps after
# reinstalling the application or re-applying the rules manually.
delete_rule() {
    local table="$1"
    local chain="$2"
    shift 2
    while iptables -t "$table" -D "$chain" "$@" >/dev/null 2>&1; do
        :
    done
}

ensure_chain() {
    local table="$1"
    local chain="$2"
    if iptables -t "$table" -L "$chain" -n >/dev/null 2>&1; then
        iptables -t "$table" -F "$chain"
    else
        iptables -t "$table" -N "$chain"
    fi
}

# 设置策略路由
ip rule add fwmark 1 table 100 2>/dev/null || true
ip route add local 0.0.0.0/0 dev lo table 100 2>/dev/null || true

# Remove the jumps before rebuilding the chains.  In particular, a chain that
# is still referenced can be flushed, but must not be deleted and recreated.
delete_rule mangle PREROUTING -j V2RAY
delete_rule mangle OUTPUT -j V2RAY_MASK
delete_rule mangle PREROUTING -p tcp -m socket -j DIVERT

# 代理局域网设备
ensure_chain mangle V2RAY
iptables -t mangle -A V2RAY -d 127.0.0.1/32 -j RETURN
iptables -t mangle -A V2RAY -d 224.0.0.0/4 -j RETURN
iptables -t mangle -A V2RAY -d 255.255.255.255/32 -j RETURN
iptables -t mangle -A V2RAY -d 192.168.0.0/16 -p tcp -j RETURN # 直连局域网，避免 V2Ray 无法启动时无法连网关的 SSH，如果你配置的是其他网段（如 10.x.x.x 等），则修改成自己的
iptables -t mangle -A V2RAY -d 192.168.0.0/16 -p udp ! --dport 53 -j RETURN # 直连局域网，53 端口除外（因为要使用 V2Ray 的 DNS）
# iptables -t mangle -A V2RAY -p udp --dport 443 -j DROP # 丢弃 QUIC 协议 udp 包，规避已知的很多兼容性问题，比如 V2Ray 对于预设的域名路由规则在 QUIC 协议下不生效等问题
# iptables -t mangle -A V2RAY -p udp --dport 80 -j DROP # 丢弃 QUIC 协议 udp 包
iptables -t mangle -A V2RAY -j RETURN -m mark --mark 0xff # 直连 SO_MARK 为 0xff 的流量(0xff 是 16 进制数，数值上等同与上面V2Ray 配置的 255)，此规则目的是解决v2ray占用大量CPU（https://github.com/v2ray/v2ray-core/issues/2621）
iptables -t mangle -A V2RAY -p udp -j TPROXY --on-ip 127.0.0.1 --on-port 12345 --tproxy-mark 1 # 给 UDP 打标记 1，转发至 12345 端口
iptables -t mangle -A V2RAY -p tcp -j TPROXY --on-ip 127.0.0.1 --on-port 12345 --tproxy-mark 1 # 给 TCP 打标记 1，转发至 12345 端口
iptables -t mangle -A PREROUTING -j V2RAY # 应用规则

# 代理网关本机
ensure_chain mangle V2RAY_MASK
iptables -t mangle -A V2RAY_MASK -d 224.0.0.0/4 -j RETURN
iptables -t mangle -A V2RAY_MASK -d 255.255.255.255/32 -j RETURN
iptables -t mangle -A V2RAY_MASK -d 192.168.0.0/16 -p tcp -j RETURN # 直连局域网
iptables -t mangle -A V2RAY_MASK -d 192.168.0.0/16 -p udp ! --dport 53 -j RETURN # 直连局域网，53 端口除外（因为要使用 V2Ray 的 DNS）
# Mieru is a native sidecar and cannot set SO_MARK itself. Match its
# dedicated Linux user before the generic OUTPUT mark so its upstream sockets
# always bypass TPROXY and cannot loop back through the Mieru SOCKS inbound.
MIERU_USER="${MIERU_USER:-mieru}"
if id -u "$MIERU_USER" >/dev/null 2>&1; then
    iptables -t mangle -A V2RAY_MASK -m owner --uid-owner "$MIERU_USER" -j RETURN
fi
iptables -t mangle -A V2RAY_MASK -j RETURN -m mark --mark 0xff # 直连 SO_MARK 为 0xff 的流量(0xff 是 16 进制数，数值上等同与上面V2Ray 配置的 255)，此规则目的是避免代理本机(网关)流量出现回环问题
iptables -t mangle -A V2RAY_MASK -p udp -j MARK --set-mark 1 # 给 UDP 打标记,重路由
iptables -t mangle -A V2RAY_MASK -p tcp -j MARK --set-mark 1 # 给 TCP 打标记，重路由
iptables -t mangle -A OUTPUT -j V2RAY_MASK # 应用规则

# 新建 DIVERT 规则，避免已有连接的包二次通过 TPROXY，理论上有一定的性能提升
ensure_chain mangle DIVERT
iptables -t mangle -A DIVERT -j MARK --set-mark 1
iptables -t mangle -A DIVERT -j ACCEPT
iptables -t mangle -I PREROUTING -p tcp -m socket -j DIVERT
