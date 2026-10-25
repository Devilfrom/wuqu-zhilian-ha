"""数值平台：音量/语音播报次数/云台收藏点"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NUMBER_PROPS
from .helpers import entry_unique_id


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    listener = data["listener"]
    entities = []
    for did, item in coordinator.data.items():
        dev = item["device"]
        product_id = str(dev.get("productId") or "")
        supported = item.get("supported_props") or set(item.get("properties", {}))
        for prop, (label, lo, hi, step) in NUMBER_PROPS.items():
            if prop in supported:
                entities.append(WuQuNumber(
                    coordinator, did, product_id, prop, label, lo, hi, step, listener))
    async_add_entities(entities)


class WuQuNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str, product_id: str,
                 prop: str, label: str, lo: int, hi: int, step: int, listener) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._product_id = product_id
        self._prop = prop
        self._listener = listener
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_{prop}"
        self._attr_name = label
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = "档" if prop == "motorPointIndex" else None

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data[self._id].get("properties", {}).get(self._prop)
        if val is None or val == "":
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._listener.send_control(
            self._product_id, self._id, {self._prop: int(value)})
        self.coordinator.notify_command_sent()
