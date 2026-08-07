#!/usr/bin/env bash

# This script is intentionally safe to run repeatedly.  It is called both by
# the first successful node application and by mihomo_iptable.service at boot.
set -u

TPROXY_PORT="${V2RAYPI_TPROXY_PORT:-12345}"
DNS_PORT="${V2RAYPI_DNS_PORT:-1053}"

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

# iptables chains live in the kernel, not on disk, so a device updated in place
# still carries the chains installed by the Xray-era script.  Their jumps would
# run alongside the new ones and process every packet twice.  Removing them is
# unconditional to keep this script idempotent.
cleanup_legacy_chains() {
    delete_rule mangle PREROUTING -j V2RAY
    delete_rule mangle OUTPUT -j V2RAY_MASK
    for chain in V2RAY V2RAY_MASK; do
        iptables -t mangle -F "$chain" >/dev/null 2>&1 || true
        iptables -t mangle -X "$chain" >/dev/null 2>&1 || true
    done
}

# Detect the LAN network used by this side-router instead of assuming
# 192.168.0.0/16.  The default route interface is normally the interface
# shared with the main router; V2RAYPI_LAN_CIDR can override this for hosts
# with multiple addresses/interfaces.
detect_lan_cidr() {
    local iface
    iface=$(ip route show default 2>/dev/null | awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')
    if [ -n "$iface" ]; then
        ip -o -4 addr show dev "$iface" scope global 2>/dev/null | awk 'NR == 1 { print $4; exit }'
    fi
}

LAN_CIDR="${V2RAYPI_LAN_CIDR:-$(detect_lan_cidr)}"
LAN_CIDR="${LAN_CIDR:-192.168.0.0/16}"
TRAFFIC_UP_CHAIN="V2RAYPI_TRAFFIC_UP"
TRAFFIC_DOWN_CHAIN="V2RAYPI_TRAFFIC_DOWN"

cleanup_legacy_chains

# 设置策略路由
ip rule add fwmark 1 table 100 2>/dev/null || true
ip route add local 0.0.0.0/0 dev lo table 100 2>/dev/null || true

# Remove the jumps before rebuilding the chains.  In particular, a chain that
# is still referenced can be flushed, but must not be deleted and recreated.
delete_rule mangle PREROUTING -j MIHOMO
delete_rule mangle OUTPUT -j MIHOMO_MASK
delete_rule mangle PREROUTING -p tcp -m socket -j DIVERT
delete_rule mangle PREROUTING -s "$LAN_CIDR" ! -d "$LAN_CIDR" -j "$TRAFFIC_UP_CHAIN"
delete_rule mangle FORWARD ! -s "$LAN_CIDR" -d "$LAN_CIDR" -j "$TRAFFIC_DOWN_CHAIN"
delete_rule mangle OUTPUT ! -s "$LAN_CIDR" -d "$LAN_CIDR" -j "$TRAFFIC_DOWN_CHAIN"
delete_rule nat PREROUTING -j MIHOMO_DNS
delete_rule nat OUTPUT -j MIHOMO_DNS_OUT

# These chains contain one RETURN rule each.  Their byte counters are read by
# core/traffic_monitor.py and measure client-facing traffic, rather than the
# aggregate counters of the whole host.
ensure_chain mangle "$TRAFFIC_UP_CHAIN"
iptables -t mangle -A "$TRAFFIC_UP_CHAIN" -j RETURN
ensure_chain mangle "$TRAFFIC_DOWN_CHAIN"
iptables -t mangle -A "$TRAFFIC_DOWN_CHAIN" -j RETURN

# 代理局域网设备
ensure_chain mangle MIHOMO
iptables -t mangle -A MIHOMO -d 127.0.0.1/32 -j RETURN
iptables -t mangle -A MIHOMO -d 224.0.0.0/4 -j RETURN
iptables -t mangle -A MIHOMO -d 255.255.255.255/32 -j RETURN
# TPROXY is a terminating action, so a DNS packet it accepts never reaches the
# nat table.  Let port 53 fall through here and hand it to mihomo's own DNS
# server through the nat REDIRECT rules installed further down.
iptables -t mangle -A MIHOMO -p udp --dport 53 -j RETURN
iptables -t mangle -A MIHOMO -p tcp --dport 53 -j RETURN
iptables -t mangle -A MIHOMO -d "$LAN_CIDR" -p tcp -j RETURN # 直连局域网，避免 mihomo 无法启动时无法连网关的 SSH，如果你配置的是其他网段（如 10.x.x.x 等），则修改成自己的
iptables -t mangle -A MIHOMO -d "$LAN_CIDR" -p udp -j RETURN # 直连局域网，DNS 已在上面放行给 nat 表处理
iptables -t mangle -A MIHOMO -j RETURN -m mark --mark 0xff # 直连 SO_MARK 为 0xff 的流量(0xff 是 16 进制数，数值上等同于 mihomo 配置的 routing-mark: 255)，此规则目的是避免代理自身出站流量出现回环
iptables -t mangle -A MIHOMO -p udp -j TPROXY --on-ip 127.0.0.1 --on-port "$TPROXY_PORT" --tproxy-mark 1 # 给 UDP 打标记 1，转发至 tproxy 端口
iptables -t mangle -A MIHOMO -p tcp -j TPROXY --on-ip 127.0.0.1 --on-port "$TPROXY_PORT" --tproxy-mark 1 # 给 TCP 打标记 1，转发至 tproxy 端口
iptables -t mangle -A PREROUTING -j MIHOMO # 应用规则

# 代理网关本机
ensure_chain mangle MIHOMO_MASK
iptables -t mangle -A MIHOMO_MASK -d 224.0.0.0/4 -j RETURN
iptables -t mangle -A MIHOMO_MASK -d 255.255.255.255/32 -j RETURN
iptables -t mangle -A MIHOMO_MASK -p udp --dport 53 -j RETURN # 本机 DNS 交给 nat 表重定向到 mihomo
iptables -t mangle -A MIHOMO_MASK -p tcp --dport 53 -j RETURN
iptables -t mangle -A MIHOMO_MASK -d "$LAN_CIDR" -p tcp -j RETURN # 直连局域网
iptables -t mangle -A MIHOMO_MASK -d "$LAN_CIDR" -p udp -j RETURN # 直连局域网
iptables -t mangle -A MIHOMO_MASK -j RETURN -m mark --mark 0xff # 直连 SO_MARK 为 0xff 的流量，避免代理本机(网关)流量出现回环
iptables -t mangle -A MIHOMO_MASK -p udp -j MARK --set-mark 1 # 给 UDP 打标记,重路由
iptables -t mangle -A MIHOMO_MASK -p tcp -j MARK --set-mark 1 # 给 TCP 打标记，重路由
iptables -t mangle -A OUTPUT -j MIHOMO_MASK # 应用规则

# 把 DNS 查询交给 mihomo 自己的 DNS 服务器，而不是原样转发到目标地址。
ensure_chain nat MIHOMO_DNS
iptables -t nat -A MIHOMO_DNS -s "$LAN_CIDR" -p udp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A MIHOMO_DNS -s "$LAN_CIDR" -p tcp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A PREROUTING -j MIHOMO_DNS

# 网关本机的 DNS 同样交给 mihomo，避免本机解析被污染。mihomo 自身出站带
# routing-mark 255，先 RETURN 防止它的上游查询被重定向回自己。
ensure_chain nat MIHOMO_DNS_OUT
iptables -t nat -A MIHOMO_DNS_OUT -m mark --mark 0xff -j RETURN
iptables -t nat -A MIHOMO_DNS_OUT -p udp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A MIHOMO_DNS_OUT -p tcp --dport 53 -j REDIRECT --to-ports "$DNS_PORT"
iptables -t nat -A OUTPUT -j MIHOMO_DNS_OUT

# Count the client-facing download leg.  FORWARD is used for direct traffic;
# OUTPUT is used for traffic emitted by the transparent proxy.  A response
# arriving from the upstream server to the local proxy is neither, so it is
# not double-counted.
iptables -t mangle -A FORWARD ! -s "$LAN_CIDR" -d "$LAN_CIDR" -j "$TRAFFIC_DOWN_CHAIN"
iptables -t mangle -A OUTPUT ! -s "$LAN_CIDR" -d "$LAN_CIDR" -j "$TRAFFIC_DOWN_CHAIN"

# 新建 DIVERT 规则，避免已有连接的包二次通过 TPROXY，理论上有一定的性能提升
ensure_chain mangle DIVERT
iptables -t mangle -A DIVERT -j MARK --set-mark 1
iptables -t mangle -A DIVERT -j ACCEPT
iptables -t mangle -I PREROUTING -p tcp -m socket -j DIVERT

# Count every client packet before DIVERT/TPROXY can consume it.  This counts
# each upload once, including established transparent-proxy TCP packets.
iptables -t mangle -I PREROUTING 1 -s "$LAN_CIDR" ! -d "$LAN_CIDR" -j "$TRAFFIC_UP_CHAIN"
