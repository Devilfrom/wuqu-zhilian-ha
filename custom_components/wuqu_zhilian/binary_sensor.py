"""二进制传感器平台：设备在线状态"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import entry_unique_id


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    async_add_entities(
        WuQuOnlineSensor(coordinator, did) for did in coordinator.data
    )


class WuQuOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(self, coordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._id = device_id
        dev = coordinator.data[device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{device_id}_online"

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "物趣智联",
            "model": dev.get("productId"),
        }

    @property
    def is_on(self) -> bool:
        return str(
            self.coordinator.data[self._id]["device"].get("onLineState", "")
        ) in ("1", "true", "online", "ON")
