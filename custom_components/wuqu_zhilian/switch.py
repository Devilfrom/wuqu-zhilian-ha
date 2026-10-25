"""开关平台：逗宠(猫叫播放) + 布尔控制属性，全部走 WS 控制通道"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BOOLEAN_SWITCH_PROPS, DOMAIN, PROP_PETTING
from .drive import WuQuDriveSwitch, WuQuTurnSwitch
from .helpers import entry_unique_id

# Petting 枚举：0=停止 1=开始 2=正在逗宠(设备上报态)
PETTING_ON_VALUES = ("1", "2")


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    listener = data["listener"]
    entities = []
    for did, item in coordinator.data.items():
        dev = item["device"]
        product_id = str(dev.get("productId") or "")
        supported = item.get("supported_props") or set(item.get("properties", {}))
        props = item.get("properties", {})
        if "motorControl" in supported:
            entities.append(WuQuDriveSwitch(coordinator, did, product_id, listener, dev))
            entities.append(WuQuTurnSwitch(coordinator, did, product_id, listener, dev, left=True))
            entities.append(WuQuTurnSwitch(coordinator, did, product_id, listener, dev, left=False))
        if PROP_PETTING in props:
            entities.append(WuQuPettingSwitch(coordinator, did, product_id, listener))
        for prop, label in BOOLEAN_SWITCH_PROPS.items():
            if prop in props and prop != "charge":
                entities.append(WuQuPropSwitch(
                    coordinator, did, product_id, prop, label, listener))
    async_add_entities(entities)


class _WuQuSwitchBase(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str, product_id: str, listener) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._product_id = product_id
        self._listener = listener

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    async def _send(self, prop: str, value) -> None:
        await self._listener.send_control(self._product_id, self._id, {prop: value})
        self.coordinator.notify_command_sent()


class WuQuPettingSwitch(_WuQuSwitchBase):
    """逗宠开关：on=播放猫叫逗宠(Petting:1)，off=停止(Petting:0)；状态1/2均为on"""

    _attr_translation_key = "petting"

    def __init__(self, coordinator, dev_device_id: str, product_id: str, listener) -> None:
        super().__init__(coordinator, dev_device_id, product_id, listener)
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_petting"

    @property
    def is_on(self) -> bool | None:
        val = self.coordinator.data[self._id].get("properties", {}).get(PROP_PETTING)
        if val is None:
            return None
        return str(val) in PETTING_ON_VALUES

    async def async_turn_on(self, **kwargs):
        await self._send(PROP_PETTING, 1)

    async def async_turn_off(self, **kwargs):
        await self._send(PROP_PETTING, 0)


class WuQuPropSwitch(_WuQuSwitchBase):
    """通用布尔属性开关（语音/移动侦测/缺粮提醒等）"""

    def __init__(self, coordinator, dev_device_id: str, product_id: str,
                 prop: str, label: str, listener) -> None:
        super().__init__(coordinator, dev_device_id, product_id, listener)
        self._prop = prop
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_{prop}"
        self._attr_name = label

    @property
    def is_on(self) -> bool | None:
        val = self.coordinator.data[self._id].get("properties", {}).get(self._prop)
        if val is None:
            return None
        return str(val) in ("1", "true", "True")

    async def async_turn_on(self, **kwargs):
        await self._send(self._prop, 1)

    async def async_turn_off(self, **kwargs):
        await self._send(self._prop, 0)
