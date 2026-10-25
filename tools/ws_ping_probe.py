"""物趣智联 WS 保活探针：持续向设备发送 ping=1（验证APP在线标识）

用途：配合 HA 视频发现页做直播频道探测。
假设：设备可能只在收到 APP 在线心跳(ping)后才向 Agora 推流。
App 打开视频页时会周期性发 ping；本脚本模拟该行为。

用法:
  python ws_ping_probe.py                  # 默认设备 + 每 2 秒 ping=1，Ctrl+C 停
  python ws_ping_probe.py --interval 3 --count 100
"""
import argparse
import json
import sys
import time

import websocket

import wuqu_client as w

DEVICE_ID = "2004035886068654109"
PRODUCT_ID = "72eb4594"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0, help="ping 间隔秒")
    ap.add_argument("--count", type=int, default=0, help="发送次数，0=无限")
    ap.add_argument("--value", type=int, default=1, help="ping 值")
    args = ap.parse_args()

    c = w.WuQuClient()
    token = c.ws_token()
    url = f"{w.WS_BASE}{token}?:X_Access_Token={token}"
    print(f"[WS] 连接 {url[:80]}...")

    ws = websocket.create_connection(
        url, header=[f"token: {c.token}", f"client-id: {w.CLIENT_ID}"], timeout=15
    )
    print("[WS] 已连接，开始发送 ping（打开 App 视频页的同时运行本脚本）")

    cmd = w.WuQuClient.build_cmd(PRODUCT_ID, DEVICE_ID, "WRITE_PROPERTY", {"ping": args.value})
    n = 0
    try:
        while True:
            ws.send(cmd)
            n += 1
            try:
                ws.settimeout(1.0)
                ack = ws.recv()
                print(f"[{n}] ping={args.value} -> {ack[:160]}")
            except websocket.WebSocketTimeoutException:
                print(f"[{n}] ping={args.value} -> (无回执)")
            except Exception as e:  # noqa: BLE001
                print(f"[{n}] recv err: {e}")
                break
            if args.count and n >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[WS] 用户中断")
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    print(f"[WS] 共发送 {n} 次 ping")


if __name__ == "__main__":
    main()
