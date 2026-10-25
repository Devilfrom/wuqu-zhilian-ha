# wuqu-zhilian-ha

物趣智联（WuQu ZhiLian / 创智乐 · Uascent 云平台）Home Assistant 自定义集成

通过逆向物趣智联 App（`cn.com.chuangzhile.wuquzhilian`）还原的云 API + WebSocket 协议，将设备接入 Home Assistant。已在「创智乐逗宠机器人100W」上全链路验证（登录/状态/控制）。

> 协议逆向全过程见 [docs/protocol.md](docs/protocol.md)（含 StringFog 解密、SIG 防重放签名、RSA 登录、物模型、WS 控制通道等细节）。

## 功能

- **账号登录**：手机号 + 密码（RSA 加密），自动完成 SIG 密钥协商
- **设备**：逗宠机器人等 Uascent 平台设备，物模型驱动的实体生成
- **实体**：
  - 开关：逗宠(猫叫 `Petting`)、语音、移动侦测等布尔属性
  - 选择：红外夜视 / 清晰度 / 灵敏度 / 云台方向（方向指令 3 秒自动回停）
  - 数值：音量 / 语音播报次数 / 云台收藏点
  - 传感器：电量 / 信号强度 / 轮速
  - 二进制传感器：在线状态
  - 摄像头：`pictureUrl` 快照通道（移动侦测触发时设备上传的图片）
- **控制通道**：WebSocket `WRITE_PROPERTY`（实测 HTTP reportProperty 仅受理不执行）
- **状态同步**：30 秒轮询 + 指令下发后 4 秒快速回读（云端无属性推送，详见协议文档）

## 安装

### HACS（推荐）

添加自定义仓库 `https://github.com/Devilfrom/wuqu-zhilian-ha`，类别 Integration，然后搜索安装「WuQu ZhiLian (物趣智联)」。

### 手动

```bash
cd config/custom_components
git clone https://github.com/Devilfrom/wuqu-zhilian-ha
ln -s wuqu-zhilian-ha/custom_components/wuqu_zhilian wuqu_zhilian
```

重启 Home Assistant。

## 配置

设置 → 设备与服务 → 添加集成 → 搜索「物趣智联」：

1. 输入物趣智联 App 的账号密码（与 App 登录一致）
2. 多家庭时选择要接入的家庭

## 支持的设备

| 设备 | 状态 |
|---|---|
| 创智乐逗宠机器人100W（逗宠/猫叫/云台摄像头） | ✅ 已验证 |

其他 Uascent 平台设备理论上通用（按物模型自动生成实体），欢迎提 issue 反馈。

## 协议要点（详见 docs/protocol.md）

- 云 API：`https://api-cn.uascent-iot.com/mobile/`，请求头 `token` + `customer: chuangzhile_app` 等
- SIG 防重放：`generateKeyPair` 密钥协商 → 每请求 `random/timestamp/uid/apiVersion/sig` 头（HmacSHA1）
- 登录：`getPwdLoginPublicKey` → RSA/ECB/PKCS1v15 加密密码（`passwordType: "2"`）
- 控制：WS `wss://ws-cn.uascent-iot.com:50804/messaging/<token>`，`{type:"sub", topic:"/device-message-sender/<productId>/<deviceId>", parameter:{messageType:"WRITE_PROPERTY", properties:{...}}}`

## 已知限制

- 实时视频为 Agora RTC 流（appId/appCertificate 可从产品配置接口获取），HA 侧仅接入快照通道
- 云端无属性变更推送（App 的实时性来自 Matter 本地连接），状态同步为轮询制
- App 内 `audio` 属性写入不生效（设备固件行为），集成保留开关但可能无效

## 许可

MIT

## 致谢

- 姊妹项目：[hxj-lock-ha](https://github.com/Devilfrom/hxj-lock-ha)（慧享家云锁 HA 集成）
