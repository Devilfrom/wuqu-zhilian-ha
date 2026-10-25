"""物趣智联异步 API 客户端（aiohttp，协议 2026-10-25 全链路实测验证）

验证过的协议要点：
- SIG 防重放：bootstrap(system/time+findPublicKey+generateKeyPair) → 每请求
  random/timestamp(秒)/uid/apiVersion/sig 头，sig=HmacSHA1(secret, "timestamp=..&uid=..&query_params=sha256(body)&apiVersion=5.0&random=..")
  query_params=sha256(实际发送字节)，空 body 用 App 占位符
- customer 头必须是 chuangzhile_app（smartlyn 是另一个字段，错则 500 请用户配置信息）
- 登录：RSA PKCS1v15(裸 Base64 SPKI 公钥) 加密密码，passwordType="2"+keyParam
- 属性：POST userDevice/properties/latest {deviceId, productId} → [{property, value,...}]
- 控制：WS WRITE_PROPERTY（HTTP reportProperty 仅受理不生效）
- WS token：POST /user/token/websocketToken {"expires_in":"86400"} + client-id 头
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import random as _random
import string
import time
import uuid
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_ROOT = "https://api-cn.uascent-iot.com/"
API_MOBILE = API_ROOT + "mobile/"
WS_TOKEN_URL = API_ROOT + "user/token/websocketToken"
WS_BASE = "wss://ws-cn.uascent-iot.com:50804/messaging/"
CLIENT_ID = "Y2fupRc8QQ85PNAD"
API_VERSION = "5.0"
EMPTY_BODY_SHA = "93b0c44298f46y149afbf4c8v969895403ae41e4649e834ca415991b7852b855"

BASE_HEADERS = {
    "language": "zh",
    "h5Language": "zh",
    "platform": "android",
    "channel": "1",
    "appVersionName": "1.1.6",
    "appVersionCode": "22",
    "phoneModel": "HomeAssistant",
    "phoneBrand": "HA",
    "systemVersion": "15",
    "customer": "chuangzhile_app",
    "packageName": "cn.com.chuangzhile.wuquzhilian",
    "timeZoneName": "Asia/Shanghai",
    "envType": "1",
    "serviceChannel": "1",
    "token": "",
}


class WuQuAuthError(Exception):
    """token 失效或凭据错误"""


class WuQuApiError(Exception):
    """业务错误"""


def _rsa_encrypt(text: str, public_key: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pk = "".join(public_key.split())
    if pk.startswith("-----"):
        key = serialization.load_pem_public_key(pk.encode())
    else:
        key = serialization.load_der_public_key(base64.b64decode(pk))
    return base64.b64encode(key.encrypt(text.encode(), padding.PKCS1v15())).decode()


class WuQuClient:
    """带 SIG 签名的物趣智联云客户端"""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.token = ""
        self.sig_uid = ""
        self.sig_secret = ""
        self.time_offset = 0  # 秒

    def _headers(self, extra: dict | None = None) -> dict:
        h = {**BASE_HEADERS, "token": self.token}
        if extra:
            h.update(extra)
        return h

    def _sig_headers(self, body_bytes: bytes) -> dict:
        if not self.sig_secret:
            return {}
        random_hex = uuid.uuid4().hex
        ts = int(time.time()) + self.time_offset
        qp = hashlib.sha256(body_bytes).hexdigest() if body_bytes else EMPTY_BODY_SHA
        base = (f"timestamp={ts}&uid={self.sig_uid}&query_params={qp}"
                f"&apiVersion={API_VERSION}&random={random_hex}")
        sig = quote(base64.b64encode(
            hmac.new(self.sig_secret.encode(), base.encode(), hashlib.sha1).digest()
        ).decode(), safe="")
        return {"random": random_hex, "timestamp": str(ts), "uid": self.sig_uid,
                "apiVersion": API_VERSION, "sig": sig}

    async def _post(self, url: str, payload: dict | None = None, extra_headers: dict | None = None) -> object:
        if payload:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        else:
            body = b""
        headers = self._headers(extra_headers) | self._sig_headers(body) | {"Content-Type": "application/json"}
        async with self._session.post(url, data=body, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=15)) as resp:
            text = await resp.text()
            try:
                envelope = json.loads(text)
            except ValueError as err:
                raise WuQuApiError(f"{url} 非JSON响应: {text[:120]}") from err
        code = envelope.get("code")
        if code != 0:
            msg = f"{url} code={code} msg={envelope.get('message')}"
            if code in (34,):
                raise WuQuAuthError(msg)
            raise WuQuApiError(msg)
        return envelope.get("data")

    # ---------- SIG 引导 ----------
    async def async_sig_bootstrap(self) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        t = await self._post(API_ROOT + "user/go/app/sign/system/time")
        server_sec = int(str(t).strip())
        if server_sec > 9999999999:
            server_sec //= 1000
        self.time_offset = server_sec - int(time.time())
        server_pub = str(await self._post(API_ROOT + "user/go/app/sign/findPublicKey")).strip()
        kp = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_b64 = base64.b64encode(kp.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        random8 = "".join(_random.choices(string.ascii_letters + string.digits, k=8))
        resp = await self._post(API_ROOT + "user/go/app/sign/generateKeyPair",
                                {"clientPublicKey": pub_b64, "value": _rsa_encrypt(random8, server_pub)})
        info = json.loads(kp.decrypt(base64.b64decode(resp), padding.PKCS1v15()).decode())
        self.sig_uid = info["clientId"]
        self.sig_secret = info["secret"]
        _LOGGER.info("物趣智联 SIG 协商完成 uid=%s", self.sig_uid)

    # ---------- 认证 ----------
    async def async_login(self, username: str, password: str) -> dict:
        if not self.sig_secret:
            await self.async_sig_bootstrap()
        key_info = await self._post(API_MOBILE + "app_user/go/getPwdLoginPublicKey", {})
        data = await self._post(API_MOBILE + "app_user/login", {
            "username": username,
            "password": _rsa_encrypt(password, key_info["publicKey"]),
            "timeZone": "Asia/Shanghai",
            "countryCode": "CN",
            "passwordType": "2",
            "keyParam": key_info.get("keyParam", ""),
        })
        self.token = data["token"]
        return data

    # ---------- 家庭/设备 ----------
    async def async_families(self) -> list[dict]:
        return await self._post(API_MOBILE + "family/familyList", {})

    async def async_devices(self, family_id: str) -> list[dict]:
        return await self._post(API_MOBILE + "userDevice/listDevice", {"familyId": family_id})

    async def async_device_details(self, device_id: str, dev_device_id: str, product_id: str) -> dict:
        return await self._post(API_MOBILE + "userDevice/queryDeviceDetails",
                                {"id": device_id, "deviceId": dev_device_id, "productId": product_id})

    async def async_properties(self, dev_device_id: str, product_id: str) -> dict[str, object]:
        """实测端点 properties/latest；返回 {property: value}"""
        data = await self._post(API_MOBILE + "userDevice/properties/latest",
                                {"deviceId": dev_device_id, "productId": product_id})
        return {p["property"]: p["value"] for p in data or [] if "property" in p}

    async def async_report_property(self, dev_device_id: str, properties: dict) -> object:
        """HTTP 控制通道（实测仅受理，实际生效走 WS）"""
        return await self._post(API_MOBILE + "userDevice/reportProperty",
                                {"deviceId": dev_device_id, "properties": properties})

    # ---------- WebSocket ----------
    async def async_ws_token(self) -> str:
        data = await self._post(WS_TOKEN_URL, {"expires_in": "86400"},
                                extra_headers={"client-id": CLIENT_ID})
        return data["token"]

    @staticmethod
    def build_ws_cmd(product_id: str, dev_device_id: str, message_type: str, properties: dict) -> str:
        return json.dumps({
            "type": "sub",
            "id": dev_device_id,
            "topic": f"/device-message-sender/{product_id}/{dev_device_id}",
            "parameter": {
                "messageType": message_type,
                "properties": properties,
                "headers": {"async": True},
            },
        }, ensure_ascii=False)


class WuQuWsListener:
    """长连接：WRITE_PROPERTY 控制下发 + 设备推送接收"""

    def __init__(self, client: WuQuClient, on_update=None) -> None:
        self._client = client
        self._on_update = on_update
        self._ws = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    async def stop(self) -> None:
        self._stop.set()
        if self._ws:
            await self._ws.close()

    async def send_control(self, product_id: str, dev_device_id: str, properties: dict) -> bool:
        """通过 WS 下发 WRITE_PROPERTY（实测验证的控制通道）"""
        async with self._lock:
            ws = self._ws
            _LOGGER.info("物趣智联 send_control ws=%s props=%s", "已连" if ws and not ws.closed else "断开", properties)
            if ws is None or ws.closed:
                _LOGGER.warning("物趣智联 WS 未连接，控制指令丢弃(%s)", properties)
                return False
            await ws.send_str(self._client.build_ws_cmd(
                product_id, dev_device_id, "WRITE_PROPERTY", properties))
            _LOGGER.info("物趣智联 控制指令已发送 → %s", dev_device_id)
            return True

    async def run(self, session: aiohttp.ClientSession) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                token = await self._client.async_ws_token()
                url = f"{WS_BASE}{token}?:X_Access_Token={token}"
                async with session.ws_connect(
                    url,
                    headers={"token": self._client.token, "client-id": CLIENT_ID},
                    heartbeat=10,
                ) as ws:
                    self._ws = ws
                    _LOGGER.info("物趣智联 WS 已连接")
                    backoff = 1
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._dispatch(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("物趣智联 WS 断开: %s，%ds 后重连", err, backoff)
            self._ws = None
            try:
                await asyncio.wait_for(self._stop.wait(), backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)

    def _dispatch(self, raw: str) -> None:
        try:
            info = json.loads(raw)
        except ValueError:
            return
        payload = info.get("payload") or {}
        if payload.get("messageType") == "WRITE_PROPERTY_REPLY":
            _LOGGER.info("物趣智联 控制回执 success=%s code=%s", payload.get("success"), payload.get("code"))
            if not payload.get("success"):
                _LOGGER.warning("物趣智联控制指令被拒绝: %s", raw[:200])
            return
        if info.get("type") == "result" or payload.get("messageType") == "LOG":
            return
        device_id = payload.get("deviceId")
        if device_id and self._on_update:
            self._on_update(str(device_id), payload)
