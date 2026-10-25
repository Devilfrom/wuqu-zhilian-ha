"""物趣智联 视频/遥控一体化操控台

- GET  /api/wuqu_zhilian/videopage/{entry_id}/{device_id}        → 操控台页面
- POST /api/wuqu_zhilian/videopage/{entry_id}/{device_id}/motor  → 遥控指令
- GET  /api/wuqu_zhilian/videopage/{entry_id}/{device_id}/status → 设备状态轮询

2026-10-25 实测协议：
- Agora 频道名 = md5(deviceId)（32 位小写 hex）；设备 uid = int(deviceId 后 8 位)
- 电机：motorControl 枚举 0停/1前进/2后退/3左/4右；**前进/后退必须带非零轮速**
- **设备保活/唤醒 = ping dp 递增心跳**（值必须 1..10 循环变化，常量无效；
  停写数秒设备 UNPUB+LEFT 退出 Agora 频道进入休眠；操控台打开即自动 3s 心跳）
- AccessToken2 为官方 Token007 算法的最小移植（仅 RTC 服务）
"""
from __future__ import annotations

import base64
import hashlib
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
from .drive import DEFAULT_DRIVE_SPEED, get_motor_state, send_motor

_LOGGER = logging.getLogger(__name__)


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


# ---------- 操控台页面 ----------
PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=0,viewport-fit=cover">
<title>__DEV_NAME__ - 遥控台</title>
<script src="/local/agora-sdk.js"></script>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#111;color:#eee;font:15px/1.5 system-ui,"PingFang SC","Microsoft YaHei";user-select:none}
.wrap{max-width:480px;margin:0 auto;padding:0 0 24px;min-height:100vh;background:#111}
header{display:flex;align-items:center;gap:10px;padding:14px 16px}
header .name{font-size:17px;font-weight:600}
header .dot{width:8px;height:8px;border-radius:50%;background:#666;margin-left:auto}
header .dot.on{background:#30d158}
.videobox{position:relative;width:100%;aspect-ratio:16/9;background:#000;overflow:hidden}
#video{width:100%;height:100%;object-fit:contain;background:#000}
.ov{position:absolute;display:flex;gap:6px;align-items:center;font-size:12px;color:#fff;
  background:rgba(0,0,0,.45);padding:4px 9px;border-radius:14px}
.ov.tl{top:8px;left:8px}.ov.tr{top:8px;right:8px}
.ov.bl{bottom:8px;left:8px}.ov.br{bottom:8px;right:8px}
.ov button{border:0;background:transparent;color:#fff;font-size:15px;padding:2px 4px;cursor:pointer}
#found{position:absolute;top:8px;left:50%;transform:translateX(-50%);z-index:9;background:#2d7d46;
  color:#fff;padding:6px 12px;border-radius:8px;font-size:12px;display:none;white-space:nowrap;
  max-width:96%;overflow:hidden;text-overflow:ellipsis}
.actions{display:flex;justify-content:space-around;padding:16px 8px 4px}
.act{display:flex;flex-direction:column;align-items:center;gap:6px;background:none;border:0;
  color:#ddd;font-size:12px;cursor:pointer;padding:6px 10px;border-radius:10px}
.act .ico{font-size:22px;width:46px;height:46px;line-height:44px;border-radius:50%;
  background:#222;text-align:center}
.act:active .ico,.act.on .ico{background:#0a84ff;color:#fff}
.act.on{color:#ff453a}
.dpad{width:248px;height:248px;border-radius:50%;background:#1c1c1e;position:relative;
  margin:18px auto 6px;touch-action:none;box-shadow:inset 0 0 0 1px #2c2c2e}
.dp{position:absolute;width:70px;height:70px;border-radius:50%;border:0;background:#2c2c2e;
  color:#ddd;font-size:22px;cursor:pointer;touch-action:none}
.dp:active,.dp.hot{background:#0a84ff;color:#fff}
.dp.up{top:6px;left:50%;margin-left:-35px}
.dp.down{bottom:6px;left:50%;margin-left:-35px}
.dp.left{left:6px;top:50%;margin-top:-35px}
.dp.right{right:6px;top:50%;margin-top:-35px}
.dp-c{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:60px;height:60px;
  border-radius:50%;background:#0a0a0a;display:flex;align-items:center;justify-content:center;
  font-size:11px;color:#666;text-align:center}
.speed{display:flex;align-items:center;gap:10px;padding:6px 34px 2px;font-size:13px;color:#999}
.speed input{flex:1;accent-color:#0a84ff}
.speed b{color:#eee;min-width:26px;text-align:right}
.petbtn{display:block;width:calc(100% - 48px);margin:14px 24px 0;padding:14px;border:0;
  border-radius:26px;background:#0a84ff;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
.petbtn:active{filter:brightness(.9)}
.petbtn.running{background:#ff453a}
#log{margin:16px 16px 0;padding:10px 12px;background:#0a0a0a;border-radius:10px;font-size:11px;
  color:#777;max-height:96px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%);background:rgba(0,0,0,.85);
  color:#fff;padding:9px 16px;border-radius:20px;font-size:13px;z-index:99;display:none;max-width:80%}
</style></head><body>
<div class="wrap">
  <header><span class="name">__DEV_NAME__</span><span id="ka" style="font-size:12px;color:#666">保活 --</span><span class="dot" id="dot"></span></header>

  <div class="videobox" id="videobox">
    <video id="video" autoplay playsinline muted></video>
    <div id="found"></div>
    <div class="ov tl"><span id="rssi">信号 --</span><span id="batt">🔋 --%</span></div>
    <div class="ov tr"><span id="speedo">--/--</span></div>
    <div class="ov bl"><button id="btnFs" title="全屏">⛶</button></div>
    <div class="ov br"><button id="btnMute" title="静音">🔇</button></div>
  </div>

  <div class="actions">
    <button class="act" id="btnSnap"><span class="ico">📷</span>截屏</button>
    <button class="act" id="btnTalk"><span class="ico">🎤</span>对讲</button>
    <button class="act" id="btnRec"><span class="ico">⏺</span>录屏</button>
  </div>

  <div class="dpad" id="dpad">
    <button class="dp up"    data-act="fwd">▲</button>
    <button class="dp left"  data-act="left">◀</button>
    <div class="dp-c">按住<br>移动</div>
    <button class="dp right" data-act="right">▶</button>
    <button class="dp down"  data-act="back">▼</button>
  </div>

  <div class="speed"><span>速度</span><input type="range" id="speed" min="10" max="100" step="5" value="__SPEED__"><b id="speedVal">__SPEED__</b></div>

  <button class="petbtn" id="btnPet">开始逗宠</button>

  <div id="log"></div>
</div>
<div class="toast" id="toast"></div>
<audio id="audio" autoplay></audio>
<script>
const CFG = __CONFIG__;
const BASE = location.pathname.replace(/\\/$/, '');
const $ = id => document.getElementById(id);
const video = $('video'), audioEl = $('audio');
const lines = [];
const logLine = m => { lines.push(m); if (lines.length > 14) lines.shift(); $('log').textContent = lines.join('\\n'); };
let toastTimer = null;
const toast = m => { const t = $('toast'); t.textContent = m; t.style.display = 'block';
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.style.display = 'none', 2200); };

/* ---------- 视频发现：主候选 md5(deviceId) 优先，其余兜底 ---------- */
const clients = [];
let activeClient = null, foundChannel = null;

CFG.channels.forEach((ch, i) => {
  setTimeout(() => {
    const client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
    client.on('user-published', async (user, mediaType) => {
      if (mediaType === 'video') {
        await client.subscribe(user, 'video');
        user.videoTrack.play('video');
        if (foundChannel !== ch.name) markFound(ch.name, user.uid, client);
      } else if (mediaType === 'audio') {
        try {
          await client.subscribe(user, 'audio');
          user.audioTrack.play('audio');
          logLine('已订阅设备音频');
        } catch (e) { logLine('音频订阅失败: ' + e.message); }
      }
    });
    client.on('user-unpublished', () => { if (foundChannel === ch.name) logLine('对方停止推流'); });
    client.join(CFG.appId, ch.name, ch.token, 0)
      .then(() => logLine('已加入 ' + ch.name.slice(0, 12)))
      .catch(e => logLine('加入失败 ' + ch.name.slice(0, 12) + ': ' + (e.message || e)));
    clients.push(client);
  }, i * 250);
});
function markFound(name, uid, client) {
  foundChannel = name; activeClient = client;
  const f = $('found');
  f.style.display = 'block';
  f.textContent = '✅ 直播频道: ' + name;
  logLine('✅ 收到画面 uid=' + uid);
}
logLine('正在并行加入 ' + CFG.channels.length + ' 个候选频道…');

/* ---------- 遥控 ---------- */
let activeAction = null;
const motor = async (action) => {
  try {
    const r = await fetch(BASE + '/motor', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, speed: +$('speed').value })
    });
    const j = await r.json();
    if (!j.ok) toast('指令失败: ' + (j.error || r.status));
    return j;
  } catch (e) { toast('网络错误: ' + e.message); }
};
function startMove(act, btn) {
  if (activeAction === act) return;
  activeAction = act;
  document.querySelectorAll('.dp').forEach(b => b.classList.remove('hot'));
  if (btn) btn.classList.add('hot');
  motor(act);
}
function stopMove() {
  if (!activeAction) return;
  activeAction = null;
  document.querySelectorAll('.dp').forEach(b => b.classList.remove('hot'));
  motor('stop');
}
document.querySelectorAll('.dp').forEach(btn => {
  const act = btn.dataset.act;
  btn.addEventListener('pointerdown', e => { e.preventDefault(); startMove(act, btn); });
  btn.addEventListener('contextmenu', e => e.preventDefault());
});
['pointerup', 'pointercancel'].forEach(ev => window.addEventListener(ev, stopMove));
/* 键盘方向键（桌面端） */
const KEYMAP = { ArrowUp: 'fwd', ArrowDown: 'back', ArrowLeft: 'left', ArrowRight: 'right' };
document.addEventListener('keydown', e => {
  const act = KEYMAP[e.key]; if (!act || e.repeat) return;
  e.preventDefault(); startMove(act, document.querySelector('.dp[data-act="' + act + '"]'));
});
document.addEventListener('keyup', e => { if (KEYMAP[e.key]) { e.preventDefault(); stopMove(); } });
/* 速度：改了就跟手重发 */
$('speed').addEventListener('input', () => { $('speedVal').textContent = $('speed').value; });
$('speed').addEventListener('change', () => { if (activeAction) motor(activeAction); });

/* ---------- 逗宠 ---------- */
const petBtn = $('btnPet');
petBtn.addEventListener('click', async () => {
  petBtn.dataset.touched = '1';
  const running = petBtn.classList.contains('running');
  const j = await motor(running ? 'unpet' : 'pet');
  if (j && j.ok) { petBtn.classList.toggle('running', !running); petBtn.textContent = running ? '开始逗宠' : '停止逗宠'; }
});

/* ---------- 截屏 ---------- */
$('btnSnap').addEventListener('click', () => {
  if (!video.videoWidth) { toast('还没有画面'); return; }
  const c = document.createElement('canvas');
  c.width = video.videoWidth; c.height = video.videoHeight;
  c.getContext('2d').drawImage(video, 0, 0);
  c.toBlob(b => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(b);
    a.download = 'snapshot_' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.png';
    a.click(); URL.revokeObjectURL(a.href);
  });
  toast('已保存截图');
});

/* ---------- 录屏 ---------- */
let recorder = null, recChunks = [];
$('btnRec').addEventListener('click', () => {
  const btn = $('btnRec');
  if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
  if (!video.videoWidth) { toast('还没有画面'); return; }
  let stream;
  try {
    stream = (video.srcObject instanceof MediaStream) ? video.srcObject : video.captureStream();
  } catch (e) { toast('录屏不支持: ' + e.message); return; }
  try {
    recChunks = [];
    recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    recorder.ondataavailable = e => { if (e.data.size) recChunks.push(e.data); };
    recorder.onstop = () => {
      const blob = new Blob(recChunks, { type: 'video/webm' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'record_' + new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19) + '.webm';
      a.click(); URL.revokeObjectURL(a.href);
      btn.classList.remove('on'); btn.querySelector('.ico').textContent = '⏺';
      recorder = null; toast('录像已保存');
    };
    recorder.start();
    btn.classList.add('on'); btn.querySelector('.ico').textContent = '⏹';
    toast('开始录像');
  } catch (e) { toast('录像启动失败: ' + e.message); }
});

/* ---------- 对讲（需安全上下文，http://IP 会被浏览器拦） ---------- */
let micTrack = null, talking = false;
$('btnTalk').addEventListener('click', async () => {
  const btn = $('btnTalk');
  if (talking) {
    try { if (activeClient) await activeClient.unpublish(micTrack); if (micTrack) micTrack.close(); } catch (e) {}
    micTrack = null; talking = false; btn.classList.remove('on'); toast('对讲结束'); return;
  }
  if (!activeClient) { toast('等待视频连接后再对讲'); return; }
  try {
    micTrack = await AgoraRTC.createMicrophoneAudioTrack({ AEC: true, ANS: true, AGC: true });
    await activeClient.publish(micTrack);
    talking = true; btn.classList.add('on'); toast('对讲中…');
  } catch (e) {
    toast('对讲不可用: ' + e.message + (location.protocol === 'http:' && location.hostname !== 'localhost' ? '（HTTP 局域网 IP 下浏览器禁用麦克风，需 HTTPS）' : ''));
  }
});

/* ---------- 全屏 / 静音 ---------- */
$('btnFs').addEventListener('click', () => {
  const el = $('videobox');
  if (document.fullscreenElement) document.exitFullscreen();
  else if (el.requestFullscreen) el.requestFullscreen();
});
let muted = true;
$('btnMute').addEventListener('click', () => {
  muted = !muted; audioEl.muted = muted;
  $('btnMute').textContent = muted ? '🔇' : '🔊';
  if (!muted) audioEl.play().catch(() => {});
});

/* ---------- 状态轮询 ---------- */
async function pollStatus() {
  try {
    const s = await (await fetch(BASE + '/status')).json();
    $('dot').classList.toggle('on', s.online === 1 || s.online === '1');
    $('rssi').textContent = '信号 ' + (s.rssi ?? '--');
    $('batt').textContent = '🔋 ' + (s.battery ?? '--') + '%';
    $('speedo').textContent = '轮速 ' + (s.leftSpeed ?? 0) + '/' + (s.rightSpeed ?? 0);
    if (s.petting === 2 || s.petting === '2') {
      petBtn.classList.add('running'); petBtn.textContent = '停止逗宠';
    } else if (!petBtn.dataset.touched) {
      petBtn.classList.remove('running'); petBtn.textContent = '开始逗宠';
    }
  } catch (e) { /* 静默 */ }
}
setInterval(pollStatus, 5000); pollStatus();

/* ---------- 保活心跳：唤醒休眠设备并保持在线 ----------
   实测（2026-10-25）：设备 ping dp 值必须递增（1..10 循环）才认，
   常量会被当陈旧数据忽略；停写数秒后设备 UNPUB+LEFT 退出 Agora 频道（休眠）。 */
let kaCount = 0;
async function keepalive() {
  try {
    const r = await fetch(BASE + '/motor', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'ping' })
    });
    const j = await r.json();
    const el = $('ka');
    if (j && j.ok) {
      kaCount++;
      el.textContent = '保活 #' + kaCount; el.style.color = '#30d158';
    } else {
      el.textContent = '保活失败'; el.style.color = '#ff453a';
    }
  } catch (e) {
    $('ka').textContent = '保活失败'; $('ka').style.color = '#ff453a';
  }
}
keepalive();
const kaTimer = setInterval(keepalive, 3000);
window.addEventListener('pagehide', () => clearInterval(kaTimer));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { clearInterval(kaTimer); }
  else { keepalive(); kaTimer = setInterval(keepalive, 3000); }
});
</script></body></html>"""


class WuQuVideoView(HomeAssistantView):
    """操控台页面（配置内联；家庭内网使用，如需加密可自行加反代）"""

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
        # ✅ 2026-10-25 实测确认：频道名 = md5(deviceId)，设备 uid = int(deviceId 后 8 位)
        md5_dev = hashlib.md5(device_id.encode()).hexdigest()
        candidates = [
            md5_dev,                                     # md5(deviceId) —— 实测频道
            device_id,                                   # deviceId
            f"{product_id}{device_id}",                  # productId+deviceId
            f"cam_{device_id}", f"live_{device_id}",     # 带前缀变体
            mac, mac.upper(),                            # mac 两种写法
            product_id,                                  # productId 单独
            md5_dev[:16],                                # md5 截断 16 位
            f"{product_id}_{device_id}",                 # 下划线连接
        ]
        seen, channels = set(), []
        for ch in candidates:
            if ch and ch not in seen:
                seen.add(ch)
                channels.append({"name": ch, "token": build_rtc_token(app_id, app_cert, ch)})
        props = item.get("properties") or {}
        st = get_motor_state(coordinator, device_id)
        cfg = {
            "appId": app_id,
            "channels": channels,
            "status": {
                "online": dev.get("onLineState"),
                "battery": props.get("batteryPercent"),
                "rssi": props.get("rssi"),
                "leftSpeed": props.get("leftSpeed"),
                "rightSpeed": props.get("rightSpeed"),
                "petting": props.get("Petting"),
            },
        }
        dev_name = str(dev.get("deviceName") or "逗宠机器人")
        html = (PAGE
                .replace("__CONFIG__", _json.dumps(cfg, ensure_ascii=False))
                .replace("__DEV_NAME__", dev_name)
                .replace("__SPEED__", str(st.speed)))
        from aiohttp import web

        return web.Response(text=html, content_type="text/html")


class WuQuMotorView(HomeAssistantView):
    """遥控指令：{action: fwd|back|left|right|stop|pet|unpet, speed: 0-100}"""

    url = "/api/wuqu_zhilian/videopage/{entry_id}/{device_id}/motor"
    name = "api:wuqu_zhilian:motor"
    requires_auth = False

    def __init__(self, hass) -> None:
        self._hass = hass

    async def post(self, request, entry_id: str, device_id: str):
        entry_data = self._hass.data.get(DOMAIN, {}).get(entry_id)
        if not entry_data:
            return self.json({"error": "config entry not found"}, status_code=404)
        coordinator = entry_data["coordinator"]
        listener = entry_data["listener"]
        item = coordinator.data.get(device_id)
        if not item:
            return self.json({"error": "device not found"}, status_code=404)
        dev = item["device"]
        product_id = str(dev.get("productId") or "")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return self.json({"error": "invalid json"}, status_code=400)
        action = str(body.get("action") or "")
        try:
            speed = int(body.get("speed", DEFAULT_DRIVE_SPEED))
        except (TypeError, ValueError):
            speed = DEFAULT_DRIVE_SPEED

        if action in ("pet", "unpet"):
            val = 1 if action == "pet" else 0
            try:
                await listener.send_control(product_id, device_id, {"Petting": val})
            except Exception as err:  # noqa: BLE001
                return self.json({"error": str(err)}, status_code=502)
            coordinator.notify_command_sent()
            return self.json({"ok": True, "action": action, "Petting": val})

        if action == "ping":
            # 设备保活：ping 值必须递增（1..10 循环）设备才认，常量会被当陈旧数据忽略
            st_ping = get_motor_state(coordinator, device_id)
            st_ping.ping_seq = st_ping.ping_seq % 10 + 1
            try:
                await listener.send_control(product_id, device_id, {"ping": st_ping.ping_seq})
            except Exception as err:  # noqa: BLE001
                return self.json({"error": str(err)}, status_code=502)
            return self.json({"ok": True, "action": "ping", "ping": st_ping.ping_seq})

        st = get_motor_state(coordinator, device_id)
        st.speed = max(0, min(100, speed))
        if action == "fwd":
            st.direction = "fwd"
            st.drive_on = True
            st.turn = None
        elif action == "back":
            st.direction = "back"
            st.drive_on = True
            st.turn = None
        elif action == "left":
            st.turn = "L"
        elif action == "right":
            st.turn = "R"
        elif action == "stop":
            st.drive_on = False
            st.turn = None
        else:
            return self.json({"error": f"unknown action: {action}"}, status_code=400)
        try:
            await send_motor(coordinator, listener, product_id, device_id)
        except Exception as err:  # noqa: BLE001
            return self.json({"error": str(err)}, status_code=502)
        st.push()
        return self.json({"ok": True, "action": action, "motorControl": st.value()})


class WuQuStatusView(HomeAssistantView):
    """设备状态轮询（电量/信号/轮速/逗宠状态）"""

    url = "/api/wuqu_zhilian/videopage/{entry_id}/{device_id}/status"
    name = "api:wuqu_zhilian:status"
    requires_auth = False

    def __init__(self, hass) -> None:
        self._hass = hass

    async def get(self, request, entry_id: str, device_id: str):
        entry_data = self._hass.data.get(DOMAIN, {}).get(entry_id)
        if not entry_data:
            return self.json({"error": "config entry not found"}, status_code=404)
        item = entry_data["coordinator"].data.get(device_id)
        if not item:
            return self.json({"error": "device not found"}, status_code=404)
        dev = item["device"]
        props = item.get("properties") or {}
        return self.json({
            "online": dev.get("onLineState"),
            "battery": props.get("batteryPercent"),
            "rssi": props.get("rssi"),
            "leftSpeed": props.get("leftSpeed"),
            "rightSpeed": props.get("rightSpeed"),
            "petting": props.get("Petting"),
        })
