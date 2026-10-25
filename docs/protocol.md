# 物趣智联（物联.apk）逆向分析报告

> 分析对象：`D:\C\Desktop\慧享家逆向\物联.apk`（MD5 `2e8f551bc6a35df018149441f2f832f2`，205MB）
> 目标：还原云云协议，制作 Home Assistant 自定义集成
> 分析日期：2026-10-24/25 · 工具：jadx + androguard + 自研 StringFog 解密器

---

## 1. App 概况

| 项 | 值 |
|---|---|
| 应用名 | 物趣智联 |
| 包名 | `cn.com.chuangzhile.wuquzhilian` |
| 版本 | 1.1.6 (22) |
| 技术栈 | 原生(Kotlin/Java) + uni-app(DCloud) + React Native 混合 |
| 云平台 | 深圳优上 Uascent IoT 白牌云（类 Tuya 模式） |
| 通道 | 云 API(HTTPS) + 实时 WS + BLE 配网 + Matter(CHIP) 本地控制 + Agora 音视频 |
| 混淆 | R8 + StringFog(Base64+XOR)，业务代码在 `czl.*`/`clz*.*` 混淆包 |

关键 SDK 包：`cn.com.uascent.{sdk,network,business,communication,networkconfig,chip.chiptool}`。
业务 API 通过 uni-app 桥 `clzb/J.java` 的 `uagw_*` 方法族暴露给 JS。

## 2. 生产环境配置（已解密还原）

```
API 基址      https://api-cn.uascent-iot.com/mobile/      ← 业务 API 前缀
场景 API      https://api-cn.uascent-iot.com/scene-linkage/
WS token     https://api-cn.uascent-iot.com/user/token/websocketToken
WebSocket    wss://ws-cn.uascent-iot.com:50804/messaging/<token>?:X_Access_Token=<token>
clientId     Y2fupRc8QQ85PNAD          （AWS 环境为 EnCnMeqwrfiiVTpz）
customer     smartlyn
packageName  cn.com.chuangzhile.wuquzhilian
```

其他环境（test/内网/美区）见 `cn/com/uascent/tool/utils/czlkfif.java`（ConfigUtil）。

## 3. 登录流程

1. `POST /mobile/app_user/go/getPwdLoginPublicKey` → `{publicKey(PEM X.509), keyParam}`
2. 密码加密：`RSA/ECB/PKCS1Padding` 公钥加密 → Base64（`czl/xm5.java`）
3. `POST /mobile/app_user/login`，JSON body：
```json
{
  "username": "...", "password": "<RSA后>", "timeZone": "...",
  "countryCode": "...", "passwordType": "...", "keyParam": "<步骤1>"
}
```
4. 响应 `BaseResponse{code=0, data:{id, mobile, token, username, temperatureUnit, loginType, countryCode}}`，
   `data.token` 即后续所有请求的 `token` 头（本地存 `user_token`）。

## 4. 业务 API 请求头（拦截器 `czl/xe5.java` + `wj4`，无 HMAC 签名）

```
token: <登录 token>
language: <zh/en>          h5Language: ...
platform: android          channel: 1
appVersionName: 1.1.6      appVersionCode: 22
phoneModel/phoneBrand/systemVersion
apiVersion: <值>           customer: smartlyn
packageName: cn.com.chuangzhile.wuquzhilian
envType: 0|1               serviceChannel: 1|2
timeZoneName: ...
Connection: close
```
注：`wj4` 在服务端启用 2025 证书版本时额外加 `RANDOM/API_VERSION/TIMESTAMP/UID/SIG` 防重放头
（配套端点 `user/go/app/sign/*`），默认不启用。SDK 层 `/v1.0/*` 接口才用 HMAC-SHA256 签名（`client-id/sign/t/sdk-id` 头），业务集成不需要。

## 5. 核心 API 面（共提取 135 个端点，完整清单见 api_endpoints.txt）

| 功能 | 端点（POST，基址 /mobile/） | 参数 |
|---|---|---|
| 家庭列表 | `family/familyList` | - |
| 设备列表 | `userDevice/listDevice` | `familyId`(, `productId`) |
| 全屋首页 | `userDevice/familyHomePage` | `familyId`, `roomId` |
| 属性查询 | `userDevice/getPropertiesLatest` | `id`(设备id) |
| 属性查询2 | `userDevice/properties/latest` | Map |
| **控制(写属性)** | `userDevice/reportProperty` | raw JSON body |
| 设备详情 | `userDevice/queryDeviceDetails` | Map |
| 群组控制 | `device/groupWriteProperty` | Map |
| 场景执行 | `sceneLinkage/appHotkeyExecute/execute` | Map |
| 产品信息 | `devProduct/devProduct/getProductInfo` | productId |

`HomeDevice` bean 关键字段：`id, deviceId, productId, deviceName, deviceIcon, mac, familyId, isPowerOn, onLineState, deviceType, endpoint, categoryKey, gatewayDeviceId, gatewayProductId, mtDeviceId...`

## 6. 实时通道（WebSocket）

1. `POST /user/token/websocketToken`（全 URL，带业务头 + `client-id`）body `{"expires_in":"86400"}` → `{token}`
2. 连接 `wss://ws-cn.uascent-iot.com:50804/messaging/<token>?:X_Access_Token=<token>`（token 同时在路径与查询参数，24h 有效，断线斐波那契重试）
3. **下发控制/订阅**（`SocketCmdUtil`）：
```json
{
  "type": "sub",
  "id": "<设备id>",
  "topic": "/device-message-sender/<productId>/<deviceId>",
  "parameter": {
    "messageType": "WRITE_PROPERTY | READ_PROPERTY | SUB_READ_PROPERTY | SUB_WRITE_PROPERTY",
    "properties": { "powerstate": 1, "brightness": 80, ... },
    "headers": { "async": true }
  }
}
```
4. **上行状态**（`PayloadInfo`）：
```json
{ "topic": "...", "type": "...", "requestId": "...",
  "payload": { "deviceId": "...", "productId": "...", "messageType": "...",
               "powerstate": "...", "complete": true } }
```
经 `UEventCenter.dispatchEvent(messageType, {panel_device_id, status, socket_message_result})` 分发。

## 7. 属性模型（从 `clzb/J.java` 控制面板桥提取）

- 开关：`powerstate` / `switch_<n>`（0/1）
- 灯光：`brightness`(0-100) `colorTemperature`(mireds 或 K，面板带 min/max) `color` `saturation`
- 窗帘：`moveToPercent` `targetTiltPercent` `windowWorkMode`
- 其他：`startUpOnOff`、`mode`、门锁/传感器类走 matter/zigbee 专属属性
- HA 集成建议按 categoryKey/deviceType 映射实体类型，属性字典透传

## 8. Matter / BLE 本地通道（暂不接入 HA）

- `cn.com.uascent.chip.chiptool`：CHIPController + `MatterUdpClient`（本地 Matter LAN/BLE 控制，配对需 fabricId/passcode）
- BLE 配网：`UASmartActivatorManager`（SmartConfig/BLE），SDK `/v1.0/*` 接口带 HMAC 签名
- HA 集成首版走云端（WS+HTTP）即可，Matter 本地控制作二期

## 9. 交付物

| 文件 | 说明 |
|---|---|
| `decrypt_all.py` | StringFog 批量解密器（10500 处/954 文件） |
| `jadx_out/` | jadx 反编译原始产物 |
| `jadx_dec/` | 解密后源码（可读） |
| `api_endpoints.txt` | 135 个业务端点清单 |
| `wuqu_client.py` | 协议 PoC：登录→家庭→设备→属性→WS 订阅→控制 |
| `custom_components/wuqu_zhilian/` | HA 自定义集成骨架 |

## 10. 实测记录（2026-10-25，全链路验证通过 ✅）

**SIG 防重放机制（静态分析时遗漏，实测逆向补全）**：
- App 每个业务请求带 `random/timestamp(秒)/uid/apiVersion/sig` 头，否则 code=34/30002/30030
- 引导：`/user/go/app/sign/system/time`(秒级时间) → `findPublicKey`(服务端RSA公钥) → 本地生成 RSA-2048 对 → `generateKeyPair{clientPublicKey, value=RSA(random8)}` → 响应用客户端公钥加密的 `{clientId, secret, expires_in}`（7200s）→ secret 作 HmacSHA1 密钥
- `sig = urlencode(base64(HmacSHA1(secret, "timestamp=<秒>&uid=<clientId>&query_params=<sha256(body字节)>&apiVersion=5.0&random=<uuid_hex>")))`；**空 body 用 App 占位符** `93b0c4...b855`（假 sha256）
- **`customer` 头必须为 `chuangzhile_app`**（错值→500 请用户配置信息）

实测结果：
- 登录 ✅ token 拿到（账号 180****3303，昵称 Cx 330）
- 家庭/设备列表 ✅ 1 台「逗宠机器人」在线（id=2039****8816 / deviceId=2004****4109 / productId=72eb4594 / mac=8c87d03455e5）
- 物模型 ✅ 32 个 dp（喂食/摄像头/云台/逗宠/提醒），`userDevice/queryDeviceDetails` 返回
- 属性读取 ✅ `userDevice/properties/latest {deviceId, productId}` → `[{property, value}]`（注意 `getPropertiesLatest` 报 35 无权限，勿用）
- **WS 控制 ✅**：`WRITE_PROPERTY` 回执 success=True；volume 60/80 双向验证生效（60 写入回读 60）
- HTTP `reportProperty` ⚠️ 受理(code=0)但设备不执行——控制一律走 WS
- `audio` 属性 ⚠️ 设备端不响应写入（回执成功但值不变），volume 正常

## 11. HA 集成部署记录（2026-10-25 完成 ✅，含逗宠功能修正）

- 部署至 VM103(192.168.1.30) `/config/custom_components/wuqu_zhilian/`
- 平台：**switch(逗宠(猫叫)Petting 0/1/2 + 语音/移动侦测)** /sensor(电量/音量/信号/灵敏度/轮速)/binary_sensor(在线)
- **逗宠功能（用户指正）**：该设备无喂食机构，`doFeed` 按钮已撤；实际功能是 `Petting` 枚举（0=停止 1=开始 2=正在逗宠），写入 1 后设备播放猫叫并移动逗宠，实测 Petting=2 生效 ✓，写入 0 停止 ✓
- 状态同步：WS 属性推送订阅(SUB_WRITE_PROPERTY)返回 SYSTEM_ERROR 未生效，靠 120s 轮询兜底（控制指令本身不受影响，秒级回执）
- 配置项预创建于 `.storage/core.config_entries`（HA 2026.6 需 `discovery_keys:{}`/`subentries:[]`/`created_at`/`minor_version` 字段，缺失会崩核心）
- **关键坑**：WS 监听任务必须用 `hass.async_create_background_task`——`async_create_task` 会被 bootstrap 追踪，卡死「启动完成」信号 → supervisor API 永久 502（甚至需重启主机恢复）
- 旧版 HA API：`async_forward_platforms` 已移除，须用 `async_forward_entry_setups`

## 12. 二期完成记录（2026-10-25）

- **推送订阅结论**：云端 WS 无账号级广播（双连接实测 0 消息）；App 实时性来自 Matter 本地订阅（CHIP ReportCallback）。云路径 = 轮询制，集成采用 30s 轮询 + 指令后 4s 快速回读
- **云台**：motorControl 枚举 0停/1上/2下/3左/4右（select 实体，方向 3s 自动回停）；motorPointIndex 收藏点 0-6（number 实体）
- **红外夜视**（关/开/自动）、**清晰度**（高/中/低）、**灵敏度**（关/低/中/高）→ select 实体；**音量**/语音播报次数 → number 实体（音量 60↔80 双向实测 ✓）
- **摄像头**：实时流为 Agora RTC（appId/appCertificate 经 batchGetProductAdvanceConfig 获取，HA 侧需原生 SDK 不现实）；接入 pictureUrl 快照通道（移动侦测触发上传）为 camera 实体
- **实体生成改为物模型驱动**（queryDeviceDetails metadata），设备不上报当前值的属性也能建实体（云台/播报次数/快照）
- **GitHub**：https://github.com/Devilfrom/wuqu-zhilian-ha（v0.2.0，手机号/账号ID/Agora证书已脱敏，含 docs/protocol.md 本报告脱敏版 + tools/wuqu_client.py PoC）

## 13. 待办

- [ ] Agora RTC 转流（若需实时画面，可做独立 add-on 用 linux SDK 转 RTSP）
- [ ] HACS custom 仓库接入（hacs.json 已可加）
