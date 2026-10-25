"""摄像头平台：pictureUrl 快照（设备移动侦测时上传的图片）

实时视频为 Agora RTC 流（需原生 SDK，appId/appCertificate 可经
devProduct/devProduct/batchGetProductAdvanceConfig 获取），HA 侧以快照方式接入。
"""
from __future__ import annotations

import logging

from homeassistant.components.camera import Camera
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PROP_PICTURE
from .helpers import entry_unique_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    entities = []
    for did, item in coordinator.data.items():
        dev = item["device"]
        supported = item.get("supported_props") or set(item.get("properties", {}))
        # 物模型带 pictureUrl 即认为有摄像头（快照通道）
        if PROP_PICTURE in supported or dev.get("categoryKey") == "camera":
            entities.append(WuQuSnapshotCamera(coordinator, did))
    async_add_entities(entities)
    if not entities:
        _LOGGER.info("物趣智联：本家庭无带快照通道的摄像头设备")


class WuQuSnapshotCamera(CoordinatorEntity, Camera):
    """显示设备最近上传的抓拍图（移动侦测触发时更新）"""

    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._id = dev_device_id
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_cam"

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    @property
    def supported_features(self) -> int:
        return 0

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        url = self.coordinator.data.get(self._id, {}).get("properties", {}).get(PROP_PICTURE)
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=session.timeout) as resp:
                if resp.status == 200:
                    return await resp.read()
                _LOGGER.debug("抓拍图拉取失败 HTTP %s: %s", resp.status, url[:100])
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("抓拍图拉取异常: %s", err)
        return None
