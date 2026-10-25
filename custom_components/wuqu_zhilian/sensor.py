"""传感器平台：电量/喂食份数等数值属性"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    StateType,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NUMERIC_SENSOR_PROPS
from .helpers import entry_unique_id

DEVICE_CLASS_MAP = {
    "batteryPercent": (SensorDeviceClass.BATTERY, PERCENTAGE),
    "rssi": (SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS),
}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    entities = []
    for did, item in coordinator.data.items():
        dev = item["device"]
        props = item.get("properties", {})
        for prop, label in NUMERIC_SENSOR_PROPS.items():
            if prop in props:
                entities.append(WuQuPropSensor(coordinator, did, prop, label))
    async_add_entities(entities)


class WuQuPropSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, dev_device_id: str, prop: str, label: str) -> None:
        super().__init__(coordinator)
        self._id = dev_device_id
        self._prop = prop
        dev = coordinator.data[dev_device_id]["device"]
        self._attr_unique_id = f"{entry_unique_id(dev)}_{dev_device_id}_{prop}"
        self._attr_name = label
        if prop in DEVICE_CLASS_MAP:
            self._attr_device_class, self._attr_native_unit_of_measurement = DEVICE_CLASS_MAP[prop]

    @property
    def device_info(self):
        dev = self.coordinator.data[self._id]["device"]
        return {
            "identifiers": {(DOMAIN, str(dev.get("deviceId") or self._id))},
            "name": dev.get("deviceName"),
            "manufacturer": "创智乐",
        }

    @property
    def native_value(self) -> StateType:
        val = self.coordinator.data[self._id].get("properties", {}).get(self._prop)
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return str(val)
