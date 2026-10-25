"""物趣智联选项流占位（刷新间隔/家庭切换，待实测后完善）"""
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init")
