"""通用小工具"""


def entry_unique_id(dev: dict) -> str:
    """设备唯一 id 前缀：mac 优先"""
    return f"wqzl_{dev.get('mac') or dev.get('deviceId') or dev.get('id')}"
