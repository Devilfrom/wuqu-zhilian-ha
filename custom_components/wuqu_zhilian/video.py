"""Agora 视频支持：AccessToken2 签发 + 播放页配置视图

- GET /api/wuqu_zhilian/video/<entry_id>/<device_id>
  → {appId, channels:[{name, token}...]}  供 www/wuqu-video.html 拉取
- AccessToken2 为官方 Token007 算法的最小移植（仅 RTC 服务）
"""
from __future__ import annotations

import base64
import hmac
import logging
import secrets
import time
import zlib
from hashlib import sha256

try:  # 独立单测时可无 homeassistant
    from homeassistant.components.http import HomeAssistantView
except ImportError:  # noqa: F401
    HomeAssistantView = object

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LOG = logging.getLogger(__name__)


# ---------- AccessToken2 最小实现（官方 Token007） ----------
def _pu16(v: int) -> bytes:
    return v.to_bytes(2, "little")


def _pu32(v: int) -> bytes:
    return v.to_bytes(4, "little")


def _pstr(b: bytes) -> bytes:
    return _pu16(len(b)) + b


class _RtcService:
    TYPE = 1
    PRIV_JOIN = 1
    PRIV_PUB_AUDIO = 2
    PRIV_PUB_VIDEO = 3

    def __init__(self, channel: str, uid: int) -> None:
        self.channel = channel.encode()
        self.uid = b"" if uid == 0 else str(uid).encode()

    def pack(self) -> bytes:
        privs = sorted([(self.PRIV_JOIN, self.expire), (self.PRIV_PUB_AUDIO, self.expire),
                        (self.PRIV_PUB_VIDEO, self.expire)])
        m = _pu16(len(privs)) + b"".join(_pu16(k) + _pu32(v) for k, v in privs)
        return _pu16(self.TYPE) + m + _pstr(self.channel) + _pstr(self.uid)
    expire = 0


def build_rtc_token(app_id: str, app_cert: str, channel: str, uid: int = 0,
                    ttl: int = 3600) -> str:
    """生成 Agora RTC Token007（join+发布权限）"""
    svc = _RtcService(channel, uid)
    svc.expire = int(time.time()) + ttl
    issue_ts = int(time.time())
    salt = secrets.randbelow(2**31)
    signing_info = (
        _pstr(app_id.encode()) + _pu32(issue_ts) + _pu32(ttl) + _pu32(salt)
        + _pu16(1) + svc.pack()
    )
    # 官方密钥派生：HMAC(HMAC(cert, issue_ts), salt) 作为最终签名密钥
    key = hmac.new(_pu32(issue_ts), app_cert.encode(), sha256).digest()
    key = hmac.new(_pu32(salt), key, sha256).digest()
    sig = hmac.new(key, signing_info, sha256).digest()
    return "007" + base64.b64encode(zlib.compress(_pstr(sig) + signing_info)).decode()


# ---------- HA 视图 ----------
PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=0">
<title>物趣智联 实时视频</title>
<script src="/local/agora-sdk.js"></script>
<style>
body{margin:0;background:#000;color:#eee;font:14px/1.5 system-ui;overflow:hidden}
#video{width:100vw;height:100vh;object-fit:contain;background:#000}
#status{position:fixed;left:0;right:0;bottom:0;padding:10px 14px;background:rgba(0,0,0,.65);font-size:13px;text-align:center;z-index:9}
#retry{position:fixed;top:10px;right:10px;z-index:9;background:#2d7d46;color:#fff;border:0;padding:8px 14px;border-radius:8px;font-size:14px}
</style></head><body>
<video id="video" autoplay playsinline muted></video>
<button id="retry" onclick="location.reload()">重新连接</button>
<div id="status">初始化…</div>
<script>
const CFG = __CONFIG__;
const $ = id => document.getElementById(id);
const log = m => { $("status").textContent = m; };
let idx = 0, playing = false, client = null;
async function tryChannel(ch) {
  log(`尝试频道 ${idx + 1}/${CFG.channels.length} …`);
  client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
  client.on("user-published", async (user, mediaType) => {
    if (mediaType !== "video") return;
    await client.subscribe(user, "video");
    user.videoTrack.play("video");
    playing = true;
    log(`✅ 收到视频流 (uid=${user.uid})`);
  });
  client.on("user-unpublished", () => { if (playing) { playing = false; log("对方停止推流"); } });
  const tk = ch.token || CFG.channels[0].token;
  await client.join(CFG.appId, ch.name, tk, 0);
  await new Promise(r => setTimeout(r, 8000));
  if (playing) return true;
  await client.leave();
  return false;
}
const LOCK = new URLSearchParams(location.search).get("ch");
(async () => {
  try {
    const list = LOCK ? [{name: LOCK, token: null}] : CFG.channels;
    for (; idx < list.length; idx++) {
      const ch = LOCK
        ? {name: LOCK, token: (CFG.channels.find(c => c.name === LOCK) || {}).token}
        : list[idx];
      if (await tryChannel(ch)) return;
    }
    log("暂无视频流（已停止尝试）。打开 App 设备视频画面后点右上角重新连接");
  } catch (e) { log("出错: " + (e.message || e)); }
})();
</script></body></html>"""


class WuQuVideoView(HomeAssistantView):
    """公开视频页（配置内联；家庭内网使用，如需加密可自行加反代）"""

    url = "/api/wuqu_zhilian/videopage/{entry_id}/{device_id}"
    name = "api:wuqu_zhilian:videopage"
    requires_auth = False

    def __init__(self, hass) -> None:
        self._hass = hass

    async def get(self, request, entry_id: str, device_id: str):
        import json as _json

        entry_data = self._hass.data.get(DOMAIN, {}).get(entry_id)
        if not entry_data:
            return self.json({"error": "config entry not found"}, status_code=404)
        client = entry_data["client"]
        coordinator = entry_data["coordinator"]
        item = coordinator.data.get(device_id)
        if not item:
            return self.json({"error": "device not found"}, status_code=404)
        dev = item["device"]
        product_id = str(dev.get("productId") or "")
        try:
            cam_cfg = await client.async_camera_config(product_id)
        except Exception as err:  # noqa: BLE001
            return self.json({"error": f"camera config: {err}"}, status_code=502)
        app_id, app_cert = cam_cfg.get("appId", ""), cam_cfg.get("appCertificate", "")
        if not app_id or not app_cert:
            return self.json({"error": "product has no agora config"}, status_code=404)
        mac = str(dev.get("mac") or "")
        candidates = [device_id] + ([mac, mac.upper()] if mac else []) + [f"{product_id}{device_id}"]
        seen, channels = set(), []
        for ch in candidates:
            if ch and ch not in seen:
                seen.add(ch)
                channels.append({"name": ch, "token": build_rtc_token(app_id, app_cert, ch)})
        cfg = {"appId": app_id, "channels": channels}
        html = PAGE.replace("__CONFIG__", _json.dumps(cfg, ensure_ascii=False))
        from aiohttp import web

        return web.Response(text=html, content_type="text/html")
