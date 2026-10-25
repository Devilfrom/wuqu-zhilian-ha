"""物趣智联 (cn.com.chuangzhile.wuquzhilian / Uascent 云) 协议 PoC 客户端
逆向自 物联.apk v1.1.6 — 详见 逆向分析报告_物趣智联.md

用法:
  python wuqu_client.py login <username> <password>
  python wuqu_client.py families
  python wuqu_client.py devices <familyId>
  python wuqu_client.py props <deviceId>
  python wuqu_client.py ws                       # 订阅实时状态(前台运行)
  python wuqu_client.py control <deviceId> <productId> <prop> <value>

依赖: pip install requests websocket-client cryptography
凭据/SIG密钥持久化到 wuqu_session.json
"""
import base64
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time
import uuid
from urllib.parse import quote

import requests

API = "https://api-cn.uascent-iot.com/mobile/"
API_ROOT = "https://api-cn.uascent-iot.com/"
WS_TOKEN_URL = "https://api-cn.uascent-iot.com/user/token/websocketToken"
WS_BASE = "wss://ws-cn.uascent-iot.com:50804/messaging/"
CLIENT_ID = "Y2fupRc8QQ85PNAD"
API_VERSION = "5.0"
EMPTY_BODY_SHA = "93b0c44298f46y149afbf4c8v969895403ae41e4649e834ca415991b7852b855"
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wuqu_session.json")

HEADERS_BASE = {
    "language": "zh",
    "h5Language": "zh",
    "platform": "android",
    "channel": "1",
    "appVersionName": "1.1.6",
    "appVersionCode": "22",
    "phoneModel": "Python",
    "phoneBrand": "ZCode",
    "systemVersion": "15",
    "apiVersion": API_VERSION,
    "customer": "chuangzhile_app",
    "packageName": "cn.com.chuangzhile.wuquzhilian",
    "timeZoneName": "Asia/Shanghai",
    "Connection": "close",
}


def _load_pub(public_key: str):
    """实测公钥为裸 Base64(SPKI DER)，兼容 PEM 格式"""
    from cryptography.hazmat.primitives import serialization
    if public_key.strip().startswith("-----"):
        return serialization.load_pem_public_key(public_key.encode())
    return serialization.load_der_public_key(base64.b64decode("".join(public_key.split())))


def rsa_encrypt(text: str, public_key: str) -> str:
    from cryptography.hazmat.primitives.asymmetric import padding
    ct = _load_pub(public_key).encrypt(text.encode(), padding.PKCS1v15())
    return base64.b64encode(ct).decode()


class WuQuClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS_BASE)
        self.token = ""
        self.sig_uid = ""
        self.sig_secret = ""
        self.time_offset_ms = 0
        self.load_session()

    # ---------- 持久化 ----------
    def load_session(self):
        if os.path.exists(SESSION_FILE):
            d = json.load(open(SESSION_FILE, encoding="utf-8"))
            self.token = d.get("token", "")
            self.user = d.get("user")
            self.sig_uid = d.get("sig_uid", "")
            self.sig_secret = d.get("sig_secret", "")
            self.time_offset_ms = d.get("time_offset_ms", 0)
            self.s.headers["token"] = self.token

    def save_session(self):
        json.dump({
            "token": self.token, "user": getattr(self, "user", None),
            "sig_uid": self.sig_uid, "sig_secret": self.sig_secret,
            "time_offset_ms": self.time_offset_ms,
        }, open(SESSION_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---------- SIG 防重放（SigParamManager/wj4 还原） ----------
    def sig_bootstrap(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        # 1. 服务器时间（计算偏移；ab4.czlkfint: 毫秒转秒，时间戳一律用秒）
        t_data = self._post(API_ROOT + "user/go/app/sign/system/time", {}, signed=False)
        server_sec = int(str(t_data).strip())
        if server_sec > 9999999999:
            server_sec //= 1000
        self.time_offset_ms = server_sec - int(time.time())
        # 2. 服务器公钥
        server_pub = str(self._post(API_ROOT + "user/go/app/sign/findPublicKey", {}, signed=False)).strip()
        # 3. 本地生成 RSA-2048 密钥对
        kp = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_b64 = base64.b64encode(
            kp.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).decode()
        random8 = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        value = rsa_encrypt(random8, server_pub)
        # 4. 上传公钥换取 {clientId, secret}
        resp = self._post(API_ROOT + "user/go/app/sign/generateKeyPair",
                          {"clientPublicKey": pub_b64, "value": value}, signed=False)
        plain = kp.decrypt(base64.b64decode(resp), padding.PKCS1v15()).decode()
        info = json.loads(plain)
        self.sig_uid = info["clientId"]
        self.sig_secret = info["secret"]
        self.save_session()
        return info

    def _sig_headers(self, body_bytes: bytes) -> dict:
        """实测规则：query_params = sha256(实际发送字节)；无 body 用 App 占位符"""
        if not self.sig_secret:
            return {}
        random_hex = uuid.uuid4().hex
        ts = int(time.time()) + self.time_offset_ms  # 秒级（字段名沿用偏移量）
        qp = hashlib.sha256(body_bytes).hexdigest() if body_bytes else EMPTY_BODY_SHA
        sign_base = (f"timestamp={ts}&uid={self.sig_uid}&query_params={qp}"
                     f"&apiVersion={API_VERSION}&random={random_hex}")
        digest = base64.b64encode(
            hmac.new(self.sig_secret.encode(), sign_base.encode(), hashlib.sha1).digest()
        ).decode()
        return {
            "random": random_hex,
            "timestamp": str(ts),
            "uid": self.sig_uid,
            "apiVersion": API_VERSION,
            "sig": quote(digest, safe=""),
        }

    # ---------- API ----------
    def _post(self, path_or_url, payload=None, signed=True):
        url = path_or_url if path_or_url.startswith("http") else API + path_or_url
        if payload:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            body_bytes = body.encode()
        else:
            body, body_bytes = "", b""
        headers = self._sig_headers(body_bytes) if signed else {}
        r = self.s.post(url, data=body_bytes, headers={**headers, "Content-Type": "application/json"},
                        timeout=15)
        r.raise_for_status()
        resp = r.json()
        if resp.get("code") != 0:
            raise RuntimeError(f"{url} 失败 code={resp.get('code')} msg={resp.get('message')}")
        return resp.get("data")

    def login(self, username: str, password: str):
        if not self.sig_secret:
            print("[SIG] 引导密钥协商...")
            self.sig_bootstrap()
        keyinfo = self._post("app_user/go/getPwdLoginPublicKey", {})
        pubkey, key_param = keyinfo["publicKey"], keyinfo.get("keyParam", "")
        enc_pwd = rsa_encrypt(password, pubkey)
        data = self._post("app_user/login", {
            "username": username,
            "password": enc_pwd,
            "timeZone": "Asia/Shanghai",
            "countryCode": "CN",
            "passwordType": "2",
            "keyParam": key_param,
        })
        self.token = data["token"]
        self.user = data
        self.s.headers["token"] = self.token
        self.save_session()
        return data

    def families(self):
        return self._post("family/familyList")

    def devices(self, family_id: str):
        return self._post("userDevice/listDevice", {"familyId": family_id})

    def home_page(self, family_id: str):
        return self._post("userDevice/familyHomePage", {"familyId": family_id, "roomId": ""})

    def properties(self, device_id: str):
        return self._post("userDevice/getPropertiesLatest", {"id": device_id})

    def report_property(self, body: dict):
        """HTTP 控制通道。body 结构与 WS WRITE_PROPERTY 的 parameter 同构（待实测微调）"""
        return self._post("userDevice/reportProperty", body)

    # ---------- WebSocket ----------
    def ws_token(self):
        resp = self._post(WS_TOKEN_URL, {"expires_in": "86400"})
        return resp["token"] if isinstance(resp, dict) else resp

    def ws_listen(self, on_message=None):
        import websocket  # websocket-client
        token = self.ws_token()
        url = f"{WS_BASE}{token}?:X_Access_Token={token}"
        ws = websocket.WebSocketApp(
            url,
            header=[f"token: {self.token}", f"client-id: {CLIENT_ID}"],
            on_message=on_message or (lambda ws_, msg: print("[WS]", msg[:500])),
            on_error=lambda ws_, err: print("[WS-ERR]", err),
            on_close=lambda ws_, code, msg: print("[WS-CLOSE]", code, msg),
        )
        print(f"[WS] 连接 {url[:90]}...")
        ws.run_forever(ping_interval=10)

    # ---------- 控制指令构造（SocketCmdUtil 还原）----------
    @staticmethod
    def build_cmd(product_id: str, device_id: str, message_type: str, properties: dict) -> str:
        return json.dumps({
            "type": "sub",
            "id": device_id,
            "topic": f"/device-message-sender/{product_id}/{device_id}",
            "parameter": {
                "messageType": message_type,
                "properties": properties,
                "headers": {"async": True},
            },
        }, ensure_ascii=False)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    c = WuQuClient()

    if cmd == "login":
        info = c.login(sys.argv[2], sys.argv[3])
        print("登录成功:", json.dumps(info, ensure_ascii=False, indent=2)[:800])
    elif cmd == "sig":
        info = c.sig_bootstrap()
        print("SIG 协商成功 clientId:", info.get("clientId"), "expires:", info.get("expires_in"))
    elif cmd == "families":
        print(json.dumps(c.families(), ensure_ascii=False, indent=2)[:3000])
    elif cmd == "devices":
        for d in c.devices(sys.argv[2]):
            print(f"{str(d.get('deviceName','?')):20s} id={d.get('id')} deviceId={d.get('deviceId')} "
                  f"productId={d.get('productId')} online={d.get('onLineState')} power={d.get('isPowerOn')} "
                  f"category={d.get('categoryKey')}")
    elif cmd == "props":
        print(json.dumps(c.properties(sys.argv[2]), ensure_ascii=False, indent=2)[:3000])
    elif cmd == "control":
        device_id, product_id, prop, value = sys.argv[2:6]
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = int(value) if value.isdigit() else value
        body = {"deviceId": device_id, "productId": product_id, "properties": {prop: value}}
        print("HTTP reportProperty:", json.dumps(c.report_property(body), ensure_ascii=False))
        print("WS 指令体(备选):", c.build_cmd(product_id, device_id, "WRITE_PROPERTY", {prop: value}))
    elif cmd == "ws":
        c.ws_listen()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
