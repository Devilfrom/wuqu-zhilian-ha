"""物趣智联常量"""
DOMAIN = "wuqu_zhilian"

CONF_FAMILY_ID = "family_id"
CONF_FAMILY_NAME = "family_name"

MIN_UPDATE_INTERVAL = 30

# 物模型常用属性名（逗宠机器人）
PROP_BATTERY = "batteryPercent"
PROP_PETTING = "Petting"
PROP_PICTURE = "pictureUrl"

# Petting 枚举：0=停止 1=开始 2=正在逗宠(设备上报态)
PETTING_ON_VALUES = ("1", "2")

# 枚举属性 → select 实体（值均为字符串，来自物模型 valueType.elements）
ENUM_SELECT_PROPS = {
    "infraredVision": ("红外夜视", [("0", "关闭"), ("1", "开启"), ("2", "自动")]),
    "ppi": ("清晰度", [("0", "高"), ("1", "中"), ("2", "低")]),
    "sensitivity": ("移动侦测灵敏度", [("0", "关闭"), ("1", "低"), ("2", "中"), ("3", "高")]),
    "motorControl": ("云台控制", [("0", "停止"), ("1", "向上"), ("2", "向下"), ("3", "向左"), ("4", "向右")]),
}
# 云台方向值（选择后 3 秒自动回停，防持续转动）
MOTOR_DIRECTIONS = ("1", "2", "3", "4")
MOTOR_AUTO_STOP_SECONDS = 3

# 数值属性 → number 实体：prop: (名称, min, max, step)
NUMBER_PROPS = {
    "volume": ("音量", 0, 100, 1),
    "voicePlayNumber": ("语音播报次数", 0, 3, 1),
    "motorPointIndex": ("云台收藏点", 0, 6, 1),
}

# 生成 sensor 的数值属性（只读）
NUMERIC_SENSOR_PROPS = {
    "batteryPercent": "电量",
    "doFeedHistory": "喂食记录份数",
    "rssi": "信号强度",
    "leftSpeed": "左轮速度",
    "rightSpeed": "右轮速度",
}

# 已知布尔控制属性 → switch 实体
BOOLEAN_SWITCH_PROPS = {
    "audio": "语音",
    "motionDetect": "移动侦测",
    "feedSlowSpeed": "慢速喂食",
    "czlLowFoodRemind": "缺粮提醒",
    "czlStuckRemind": "卡粮提醒",
    "charge": "充电",
}

# 指令下发后延迟回读秒数（无云端推送，靠快速轮询补状态）
COMMAND_REFRESH_DELAY = 4
