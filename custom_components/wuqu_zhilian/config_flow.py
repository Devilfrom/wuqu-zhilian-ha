"""物趣智联配置流：账号密码登录 → 选家庭"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .api import WuQuApiError, WuQuAuthError, WuQuClient
from .const import CONF_FAMILY_ID, CONF_FAMILY_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._login_data: dict[str, Any] = {}
        self._families: list[dict] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input:
            try:
                async with aiohttp.ClientSession() as session:
                    client = WuQuClient(session)
                    await client.async_login(
                        user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                    )
                    self._login_data = user_input | {"token": client.token}
                    self._families = await client.async_families()
            except (WuQuAuthError, WuQuApiError, aiohttp.ClientError) as err:
                _LOGGER.warning("物趣智联登录失败: %s", err)
                errors["base"] = "auth_failed"
            else:
                if len(self._families) <= 1:
                    fam = self._families[0] if self._families else {}
                    return self._create_entry(user_input, fam)
                return await self.async_step_family()
        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_family(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input:
            fam_id = user_input[CONF_FAMILY_ID]
            fam = next((f for f in self._families if str(f.get("id")) == fam_id), {})
            return self._create_entry(self._login_data, fam)
        schema = vol.Schema(
            {
                vol.Required(CONF_FAMILY_ID): vol.In(
                    {str(f.get("id")): f.get("familyName", f.get("id")) for f in self._families}
                )
            }
        )
        return self.async_show_form(step_id="family", data_schema=schema, errors=errors)

    def _create_entry(self, base: dict, family: dict) -> config_entries.ConfigFlowResult:
        return self.async_create_entry(
            title=f"物趣智联-{family.get('familyName', '默认家庭')}",
            data={
                CONF_USERNAME: base[CONF_USERNAME],
                CONF_PASSWORD: base[CONF_PASSWORD],
                CONF_FAMILY_ID: str(family.get("id", "")),
                CONF_FAMILY_NAME: family.get("familyName", ""),
                "token": base.get("token", ""),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        from .options_flow import OptionsFlowHandler

        return OptionsFlowHandler(config_entry)
