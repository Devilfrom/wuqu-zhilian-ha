"""物趣智联集成入口：客户端 → 协调器 → WS 长连接（控制+推送）"""
from __future__ import annotations

import logging

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WuQuAuthError, WuQuClient, WuQuWsListener
from .const import CONF_FAMILY_ID, DOMAIN
from .coordinator import WuQuCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH, Platform.SELECT, Platform.NUMBER, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA]


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    session = async_get_clientsession(hass)
    client = WuQuClient(session)
    try:
        # 每次启动全新登录（SIG 引导+登录共 5 个请求，成本低且 token 不过期问题）
        await client.async_login(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    except WuQuAuthError as err:
        raise ConfigEntryAuthFailed from err

    coordinator = WuQuCoordinator(hass, client, entry.data[CONF_FAMILY_ID])
    await coordinator.async_config_entry_first_refresh()

    listener = WuQuWsListener(client, coordinator.ws_update)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "listener": listener,
    }
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # 后台任务必须用 background_task，否则 bootstrap 会等待它导致启动完成信号被卡（supervisor API 502）
    ws_task = hass.async_create_background_task(listener.run(session), "wuqu_zhilian_ws")
    entry.async_on_unload(lambda: listener.stop())
    hass.data[DOMAIN][entry.entry_id]["ws_task"] = ws_task
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry) -> bool:
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        await data["listener"].stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
