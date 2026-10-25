"""遥控实体类：行驶/左转/右转 开关 + 速度档（由 switch/number 平台装配）"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import entry_unique_id

PROP_LEFT_SPEED = "leftSpeed"
PROP_RIGHT_SPEED = "rightSpeed"
PROP_LEFT_ROT = "leftRotation"
PROP_RIGHT_ROT = "rightRotation"
DRIVE_PROPS = {PROP_LEFT_SPEED, PROP_RIGHT_SPEED, PROP_LEFT_ROT, PROP_RIGHT_ROT}



class _DriveBase(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id, product_id, listener, dev) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._product_id = product_id
        self._listener = listener
        self._dev = dev

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._dev.get("deviceId") or self._id))},
            "name": self._dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    async def _send(self, props: dict) -> None:
        await self._listener.send_control(self._product_id, self._id, props)
        self.coordinator.notify_command_sent()


class WuQuDriveSwitch(_DriveBase, SwitchEntity):
    """行驶开关：开=双轮按速度档推进；关=停车"""

    _attr_translation_key = "drive"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, *ctx) -> None:
        super().__init__(*ctx)
        self._attr_unique_id = f"{entry_unique_id(self._dev)}_{self._id}_drive"

    @property
    def is_on(self) -> bool:
        return self.coordinator.drive_on.get(self._id, False)

    async def async_turn_on(self, **kwargs):
        s = self.coordinator.drive_speed.get(self._id, 50)
        await self._send({PROP_LEFT_SPEED: s, PROP_RIGHT_SPEED: s})
        self.coordinator.drive_on[self._id] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._send({PROP_LEFT_SPEED: 0, PROP_RIGHT_SPEED: 0})
        self.coordinator.drive_on[self._id] = False
        self.async_write_ha_state()


class WuQuTurnSwitch(_DriveBase, SwitchEntity):
    """转向开关：左/右原地旋转（可与行驶组合）"""

    def __init__(self, *ctx, left: bool) -> None:
        super().__init__(*ctx)
        self._left = left
        self._attr_translation_key = "turn_left" if left else "turn_right"
        self._attr_icon = "mdi:rotate-left" if left else "mdi:rotate-right"
        self._attr_unique_id = f"{entry_unique_id(self._dev)}_{self._id}_{'turnl' if left else 'turnr'}"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs):
        await self._send({(PROP_LEFT_ROT if self._left else PROP_RIGHT_ROT): 1})
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._send({(PROP_LEFT_ROT if self._left else PROP_RIGHT_ROT): 0})
        self._is_on = False
        self.async_write_ha_state()


class WuQuDriveSpeed(_DriveBase, NumberEntity):
    """行驶速度档（20-100），行驶中修改即时生效"""

    _attr_icon = "mdi:speedometer"

    def __init__(self, *ctx) -> None:
        super().__init__(*ctx)
        self._attr_unique_id = f"{entry_unique_id(self._dev)}_{self._id}_drive_speed"
        self._attr_name = "行驶速度"
        self._attr_native_min_value = 20
        self._attr_native_max_value = 100
        self._attr_native_step = 10

    @property
    def native_value(self) -> float | None:
        return float(self.coordinator.drive_speed.get(self._id, 50))

    async def async_set_native_value(self, value: float) -> None:
        v = int(value)
        self.coordinator.drive_speed[self._id] = v
        if self.coordinator.drive_on.get(self._id, False):
            await self._send({PROP_LEFT_SPEED: v, PROP_RIGHT_SPEED: v})
        self.async_write_ha_state()
