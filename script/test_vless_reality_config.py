#!/usr/bin/env python3
"""
Test script: parse a VLESS Reality URL, generate full Xray config,
and verify streamSettings.realitySettings.privateKey is non-empty.
Run from project root: ./venv/bin/python script/test_vless_reality_config.py
"""
import json
import sys
import os

# run from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VLESS_URL = (
    "vless://ad6f8370-49e7-3a58-a12b-9af3dd170f01@xnode-s-gvu6ejgg.upgreen.pp.ua:15900"
    "?security=reality&encryption=none&pbk=7Eb6ZmvtDleK6pYjXo4pQ_fm5z5Pc5cKE2jZNT3Ol3g"
    "&headerType=none&fp=chrome&type=tcp&flow=xtls-rprx-vision&sni=v1-dy.ixigua.com&sid=c47e358b3b"
)


def test_x25519_direct():
    """Call _x25519_private_key() and log any exception."""
    from core.v2ray_config import V2RayConfig

    print("=== 1. Direct _x25519_private_key() ===")
    try:
        key = V2RayConfig._x25519_private_key()
        print("  result len:", len(key), "value:", repr(key[:44] if len(key) >= 44 else key))
        if not key:
            print("  ERROR: returned empty string")
        else:
            print("  OK: non-empty")
    except Exception as e:
        print("  EXCEPTION:", type(e).__name__, e)


def test_gen_config():
    """Parse VLESS URL -> Node, build user_config, gen_config, check privateKey in JSON."""
    from core.node import Node
    from core.v2ray_config import V2RayConfig
    from core.v2ray_user_config import V2RayUserConfig

    print("\n=== 2. Parse VLESS URL -> Node ===")
    data = Node.vless_uri_to_data(VLESS_URL)
    if not data:
        print("  ERROR: vless_uri_to_data returned None")
        return
    print("  data keys:", list(data.keys()))
    print("  protocol:", data.get("protocol"), "tls:", data.get("tls"), "pbk:", bool(data.get("pbk")))

    node = Node().load_data(data)
    print("  node.protocol:", getattr(node, "protocol", None))
    print("  node.tls:", getattr(node, "tls", None))
    print("  node.pbk:", getattr(node, "pbk", None))

    print("\n=== 3. Build user_config and gen_config ===")
    user_config = V2RayUserConfig()
    user_config.node = node
    user_config.proxy_mode = V2RayUserConfig.ProxyMode.ProxyGlobal.value
    user_config.advance_config.enable_mux = True

    raw_config = V2RayConfig.gen_config(user_config, [node])
    cfg = json.loads(raw_config)

    print("\n=== 4. Inspect proxy outbound realitySettings ===")
    proxy = None
    for ob in cfg.get("outbounds", []):
        if ob.get("tag") == "proxy":
            proxy = ob
            break
    if not proxy:
        print("  ERROR: no outbound with tag 'proxy'")
        print("  outbound tags:", [o.get("tag") for o in cfg.get("outbounds", [])])
        return

    ss = proxy.get("streamSettings") or {}
    reality = ss.get("realitySettings")
    if not reality:
        print("  ERROR: streamSettings.realitySettings is missing")
        print("  streamSettings keys:", list(ss.keys()))
        return

    pk = reality.get("privateKey", "")
    print("  realitySettings.privateKey len:", len(pk))
    print("  realitySettings.privateKey value:", repr(pk[:50] + "..." if len(pk) > 50 else pk))
    if not pk:
        print("  ERROR: privateKey is empty")
    else:
        print("  OK: privateKey is non-empty")

    print("\n=== 5. Full realitySettings (privateKey truncated) ===")
    dump = dict(reality)
    if len(dump.get("privateKey", "")) > 20:
        dump["privateKey"] = dump["privateKey"][:20] + "..."
    print(json.dumps(dump, indent=2))


if __name__ == "__main__":
    test_x25519_direct()
    test_gen_config()
