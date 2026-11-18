"""Config flow for the my-PV integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_BASE, CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import (
    MyPVAuthenticationError,
    MyPVDevice,
    MyPVLocalDevice,
    MyPVMeterDevice,
)
from .const import (
    CONF_ADVANCED,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_DEVICE,
    DEVICE_TYPE_METER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
AUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


async def _probe_device(
    hass: HomeAssistant, host: str, password: str | None = None
) -> tuple[MyPVDevice | None, str | None]:
    """Probe a host and return the device and its type.

    Raises MyPVAuthenticationError when the device requires a password.
    """
    session = async_get_clientsession(hass)

    device = MyPVLocalDevice(host, password, session=session)
    try:
        if await device.connect():
            return device, DEVICE_TYPE_DEVICE
    except MyPVAuthenticationError:
        await device.disconnect()
        raise
    else:
        await device.disconnect()

    meter = MyPVMeterDevice(host, session=session)
    if await meter.connect():
        return meter, DEVICE_TYPE_METER
    await meter.disconnect()

    return None, None


def _title(model: str, serial: str, device_type: str) -> str:
    """Build a config entry title for a device."""
    if device_type == DEVICE_TYPE_METER:
        return f"{model} {serial}".strip()
    suffix = serial[6:] if len(serial) > 6 else serial
    return f"{model} {suffix}".strip()


class MyPVConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for my-PV."""

    VERSION = 1

    _host: str = ""
    _device_model: str = ""
    _device_serial_number: str = ""
    _device_type: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> MyPVOptionsFlow:
        """Return the options flow."""
        return MyPVOptionsFlow()

    async def _async_create(
        self, device: MyPVDevice, device_type: str, password: str | None
    ) -> ConfigFlowResult:
        """Create a config entry for a probed device."""
        await self.async_set_unique_id(device.serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        title = _title(device.model, device.serial_number, device_type)
        data: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_DEVICE_TYPE: device_type,
        }
        if password:
            data[CONF_PASSWORD] = password

        await device.disconnect()
        return self.async_create_entry(title=title, data=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            try:
                device, device_type = await _probe_device(self.hass, self._host)
            except MyPVAuthenticationError:
                return await self.async_step_auth()
            if device is None or device_type is None:
                errors[CONF_BASE] = "cannot_connect"
            else:
                return await self._async_create(device, device_type, None)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA, {CONF_HOST: self._host}
            ),
            errors=errors,
        )

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle password authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                device, device_type = await _probe_device(
                    self.hass, self._host, password
                )
            except MyPVAuthenticationError:
                errors[CONF_PASSWORD] = "invalid_password"
            else:
                if device is None or device_type is None:
                    errors[CONF_BASE] = "cannot_connect"
                else:
                    return await self._async_create(device, device_type, password)

        return self.async_show_form(
            step_id="auth",
            data_schema=self.add_suggested_values_to_schema(
                AUTH_SCHEMA, user_input or {}
            ),
            errors=errors,
            description_placeholders={
                "name": f"my-PV {self._device_model}".strip()
            },
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        _LOGGER.debug("Zeroconf discovery of my-PV on %s", discovery_info.ip_address)
        self._host = str(discovery_info.ip_address)
        return await self._async_discovery()

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle DHCP discovery."""
        _LOGGER.debug(
            "DHCP discovery of my-PV on %s (%s)",
            discovery_info.ip,
            format_mac(discovery_info.macaddress),
        )
        self._host = discovery_info.ip
        return await self._async_discovery()

    async def _async_discovery(self) -> ConfigFlowResult:
        """Handle a discovered device."""
        try:
            device, device_type = await _probe_device(self.hass, self._host)
        except MyPVAuthenticationError:
            return await self.async_step_discovery_auth()

        if device is None or device_type is None:
            return self.async_abort(reason="cannot_connect")

        self._device_model = device.model
        self._device_serial_number = device.serial_number
        self._device_type = device_type
        await device.disconnect()

        await self.async_set_unique_id(device.serial_number)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        self.context.update(
            {"title_placeholders": {"name": f"my-PV {self._device_model}".strip()}}
        )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=self.context["title_placeholders"],
        )

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=_title(
                    self._device_model, self._device_serial_number, self._device_type
                ),
                data={
                    CONF_HOST: self._host,
                    CONF_DEVICE_TYPE: self._device_type,
                },
            )

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders=self.context.get(
                "title_placeholders", {"name": "my-PV"}
            ),
        )

    async def async_step_discovery_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle password authentication for a discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                device, device_type = await _probe_device(
                    self.hass, self._host, password
                )
            except MyPVAuthenticationError:
                errors[CONF_PASSWORD] = "invalid_password"
            else:
                if device is None or device_type is None:
                    errors[CONF_BASE] = "cannot_connect"
                else:
                    title = _title(device.model, device.serial_number, device_type)
                    await self.async_set_unique_id(device.serial_number)
                    self._abort_if_unique_id_configured(
                        updates={CONF_HOST: self._host}
                    )
                    await device.disconnect()
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_HOST: self._host,
                            CONF_DEVICE_TYPE: device_type,
                            CONF_PASSWORD: password,
                        },
                    )

        return self.async_show_form(
            step_id="discovery_auth",
            data_schema=self.add_suggested_values_to_schema(
                AUTH_SCHEMA, user_input or {}
            ),
            errors=errors,
            description_placeholders=self.context.get(
                "title_placeholders", {"name": "my-PV"}
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                device, _ = await _probe_device(
                    self.hass, entry.data[CONF_HOST], password
                )
            except MyPVAuthenticationError:
                errors[CONF_PASSWORD] = "invalid_password"
            else:
                if device is None:
                    errors[CONF_BASE] = "cannot_connect"
                else:
                    await device.disconnect()
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_PASSWORD: password}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                AUTH_SCHEMA, user_input or {}
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )


class MyPVOptionsFlow(OptionsFlow):
    """Handle my-PV options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the my-PV options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ADVANCED,
                    default=self.config_entry.options.get(CONF_ADVANCED, False),
                ): BooleanSelector()
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
