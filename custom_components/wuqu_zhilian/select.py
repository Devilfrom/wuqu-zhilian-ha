"""选择平台：枚举属性（红外夜视/清晰度/灵敏度/云台方向）"""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENUM_SELECT_PROPS, MOTOR_AUTO_STOP_SECONDS, MOTOR_DIRECTIONS
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
        for prop, (label, options) in ENUM_SELECT_PROPS.items():
            if prop in supported:
                entities.append(WuQuEnumSelect(
                    coordinator, did, product_id, prop, label, options, listener))
    async_add_entities(entities)


class WuQuEnumSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str, product_id: str,
                 prop: str, label: str, options: list[tuple[str, str]], listener) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._product_id = product_id
        self._prop = prop
        self._listener = listener
        self._value_map = dict(options)          # 值 → 文本
        self._text_map = {v: k for k, v in options}  # 文本 → 值
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_{prop}"
        self._attr_name = label
        self._attr_options = [text for _, text in options]
        self._attr_current_option = None

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    @property
    def current_option(self) -> str | None:
        val = self.coordinator.data[self._id].get("properties", {}).get(self._prop)
        if val is None:
            return None
        return self._value_map.get(str(val))

    async def async_select_option(self, option: str) -> None:
        value = self._text_map.get(option)
        if value is None:
            return
        await self._listener.send_control(self._product_id, self._id, {self._prop: value})
        self.coordinator.notify_command_sent()
        # 云台方向为瞬时动作：数秒后自动回停
        if self._prop == "motorControl" and value in MOTOR_DIRECTIONS:
            import asyncio

            async def _auto_stop() -> None:
                await asyncio.sleep(MOTOR_AUTO_STOP_SECONDS)
                await self._listener.send_control(
                    self._product_id, self._id, {"motorControl": "0"})
                self.coordinator.notify_command_sent()

            self.hass.async_create_background_task(_auto_stop(), "wuqu_motor_stop")
