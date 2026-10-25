"""遥控实体类：行驶/左转/右转 开关（由 switch 平台装配）

实测结论（2026-10-25）：底盘行驶只认 motorControl 枚举（0停/1上=前进/2下=后退/3左/4右）；
leftSpeed/rightSpeed/leftRotation 云端写入无效。
单枚举互斥：行驶+左转 = 先转，左转关后自动恢复行驶。
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .helpers import entry_unique_id

MOTOR_STOP, MOTOR_FWD, MOTOR_BACK, MOTOR_LEFT, MOTOR_RIGHT = "0", "1", "2", "3", "4"


class _MotorState:
    """设备行驶意图（挂载在 coordinator）：drive_on + turn(L/R/None) → motorControl 值"""

    def __init__(self) -> None:
        self.drive_on = False
        self.turn = None  # None | "L" | "R"
        self.peers: list = []

    def value(self) -> str:
        if self.turn == "L":
            return MOTOR_LEFT
        if self.turn == "R":
            return MOTOR_RIGHT
        return MOTOR_FWD if self.drive_on else MOTOR_STOP

    def push(self) -> None:
        for ent in self.peers:
            ent.async_write_ha_state()


def get_motor_state(coordinator, did: str) -> _MotorState:
    states = getattr(coordinator, "motor_states", None)
    if states is None:
        states = {}
        coordinator.motor_states = states
    if did not in states:
        states[did] = _MotorState()
    return states[did]


async def send_motor(coordinator, listener, product_id: str, did: str) -> None:
    st = get_motor_state(coordinator, did)
    await listener.send_control(product_id, did, {"motorControl": st.value()})
    coordinator.notify_command_sent()


class _DriveBase(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str, product_id: str, listener, dev) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._product_id = product_id
        self._listener = listener
        self._dev = dev
        self._st = get_motor_state(coordinator, dev_device_id)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, str(self._dev.get("deviceId") or self._id))},
            "name": self._dev.get("deviceName"),
            "manufacturer": "创智乐",
        }


class WuQuDriveSwitch(_DriveBase):
    """行驶开关：开=前进(motorControl:1)，关=停车(0)；转向激活时转向优先"""

    _attr_translation_key = "drive"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, *ctx) -> None:
        super().__init__(*ctx)
        self._st.peers.append(self)
        self._attr_unique_id = f"{entry_unique_id(self._dev)}_{self._id}_drive"

    @property
    def is_on(self) -> bool:
        return self._st.drive_on

    async def async_turn_on(self, **kwargs):
        self._st.drive_on = True
        await send_motor(self.coordinator, self._listener, self._product_id, self._id)
        self._st.push()

    async def async_turn_off(self, **kwargs):
        self._st.drive_on = False
        await send_motor(self.coordinator, self._listener, self._product_id, self._id)
        self._st.push()


class WuQuTurnSwitch(_DriveBase):
    """转向开关：开=左/右转(motorControl:3/4)，关=恢复行驶或停车；左右互斥"""

    def __init__(self, *ctx, left: bool) -> None:
        super().__init__(*ctx)
        self._left = left
        self._attr_translation_key = "turn_left" if left else "turn_right"
        self._attr_icon = "mdi:rotate-left" if left else "mdi:rotate-right"
        self._st.peers.append(self)
        self._attr_unique_id = f"{entry_unique_id(self._dev)}_{self._id}_{'turnl' if left else 'turnr'}"

    @property
    def is_on(self) -> bool:
        return self._st.turn == ("L" if self._left else "R")

    async def async_turn_on(self, **kwargs):
        self._st.turn = "L" if self._left else "R"
        await send_motor(self.coordinator, self._listener, self._product_id, self._id)
        self._st.push()

    async def async_turn_off(self, **kwargs):
        if self._st.turn == ("L" if self._left else "R"):
            self._st.turn = None
            await send_motor(self.coordinator, self._listener, self._product_id, self._id)
        self._st.push()
