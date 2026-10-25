"""数据协调器：30s 轮询设备列表+属性；指令下发后快速回读补状态"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WuQuApiError, WuQuAuthError, WuQuClient
from .const import COMMAND_REFRESH_DELAY

_LOGGER = logging.getLogger(__name__)


class WuQuCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """data = {deviceId: {device, properties, supported_props}}"""

    def __init__(self, hass, client: WuQuClient, family_id: str) -> None:
        super().__init__(
            hass, _LOGGER, name="wuqu_zhilian", update_interval=timedelta(seconds=30)
        )
        self.client = client
        self.family_id = family_id
        self._model_cache: dict[str, set[str]] = {}  # deviceId → 物模型属性集合

    async def _async_model_props(self, dev: dict, dev_device_id: str) -> set[str]:
        """物模型属性集合（setup 时拉一次，跨刷新缓存）"""
        if dev_device_id in self._model_cache:
            return self._model_cache[dev_device_id]
        props: set[str] = set()
        try:
            import json as _json

            details = await self.client.async_device_details(
                str(dev.get("id") or ""), dev_device_id, str(dev.get("productId") or ""))
            meta = _json.loads(details.get("metadata") or "{}")
            props = {p["id"] for p in meta.get("properties", []) if "id" in p}
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("设备 %s 物模型拉取失败: %s", dev.get("deviceName"), err)
        self._model_cache[dev_device_id] = props
        return props

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            devices = await self.client.async_devices(self.family_id)
        except WuQuAuthError:
            raise
        except WuQuApiError as err:
            raise UpdateFailed(f"设备列表刷新失败: {err}") from err
        result: dict[str, dict[str, Any]] = {}
        for dev in devices:
            dev_device_id = str(dev.get("deviceId") or "")
            if not dev_device_id:
                continue
            props: dict[str, Any] = {}
            try:
                props = await self.client.async_properties(
                    dev_device_id, str(dev.get("productId") or "")
                )
            except WuQuApiError as err:
                _LOGGER.debug("设备 %s 属性拉取失败: %s", dev.get("deviceName"), err)
            result[dev_device_id] = {
                "device": dev,
                "properties": props,
                "supported_props": await self._async_model_props(dev, dev_device_id),
            }
        return result

    def notify_command_sent(self) -> None:
        """实体下发指令后调用：延迟数秒触发一次刷新，尽快回读新状态"""
        async_call_later(
            self.hass, COMMAND_REFRESH_DELAY,
            lambda now: self.async_request_refresh(),
        )

    def ws_update(self, dev_device_id: str, payload: dict[str, Any]) -> None:
        """WS 推送入口（保留：控制回执等，属性同步以轮询为准）"""
        entry = self.data.get(dev_device_id)
        if entry is None:
            return
        self.async_update_listeners()
