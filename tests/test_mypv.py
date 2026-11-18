"""Integration tests for the my-PV custom integration."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, patch

from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mypv_custom.const import (
    CONF_ADVANCED,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_DEVICE,
    DEVICE_TYPE_METER,
    DOMAIN,
)

ELWA2_SETUP = {
    "serialno": "1601500000000000",
    "macadr": "986D35C0AB12",
    "hwvers": "v1.5A",
    "fwversion": "e0002200",
    "mainmode": "1",
    "devmode": "1",
    "bstmode": "0",
    "ww1target": "620",
    "ww1boost": "650",
    "ww_boost_h": "35",
    "ww_targ_h": "45",
    "maxpwr": "100",
    "temp1": "543",
    "temp2": "234",
}

ELWA2_DATA = {
    "temp1": "543",
    "temp2": "234",
    "power_elwa2": "3445",
    "freq": "49965",
    "volt_mains": "238",
    "curr_mains": "150",
    "uptime": "2",
    "screen_mode_flag": "1",
    "cur_eth_mode": "0",
}

ACTHOR_SETUP = {
    "serialno": "2001000000000000",
    "macadr": "986D35C0AB34",
    "hwvers": "v1.5A",
    "fwversion": "a0020410",
    "mainmode": "6",
    "devmode": "1",
    "bstmode": "0",
    "rh1_target": "450",
    "legmode": "0",
    "legtemp": "600",
    "legton": "3",
    "legint": "7",
    "maxpwr": "100",
    "temp1": "412",
}

ACTHOR_DATA = {
    "temp1": "412",
    "power_act": "1234",
    "screen_mode_flag": "1",
    "cur_eth_mode": "1",
    "fwversionlatest": "a0020500",
    "upd_state": "1",
}


def make_device_app(
    setup: dict[str, Any], data: dict[str, Any], dev: dict[str, Any]
) -> web.Application:
    """Create a mock my-PV device application."""
    app = web.Application()
    state = {"setup": dict(setup), "data": dict(data)}

    async def mypv_dev(request: web.Request) -> web.Response:
        return web.json_response(dev)

    async def auth(request: web.Request) -> web.Response:
        return web.json_response({})

    async def setup_handler(request: web.Request) -> web.Response:
        for key, value in request.query.items():
            state["setup"][key] = value
        return web.json_response(state["setup"])

    async def data_handler(request: web.Request) -> web.Response:
        return web.json_response(state["data"])

    app.router.add_get("/mypv_dev.jsn", mypv_dev)
    app.router.add_get("/auth.jsn", auth)
    app.router.add_post("/auth.jsn", auth)
    app.router.add_get("/setup.jsn", setup_handler)
    app.router.add_get("/data.jsn", data_handler)
    app["state"] = state
    return app


def make_meter_app() -> web.Application:
    """Create a mock my-PV WiFi Meter application."""
    app = web.Application()
    state = {"ct": 1}

    async def mypv_dev(request: web.Request) -> web.Response:
        return web.json_response(
            {"sn": "1234567890", "device": "Wi-Fi Meter", "fwversion": "1.0"}
        )

    async def monitor(request: web.Request) -> web.Response:
        return web.json_response(
            {
                "Datas": {
                    "0": [230.1, 1.5, 345.0, 100.0, 50.0, 50.0],
                    "1": [230.2, 2.5, 575.0, 101.0, 51.0, 50.0],
                    "2": [230.3, 0.5, 115.0, 102.0, 52.0, 50.0],
                }
            }
        )

    async def ct_get(request: web.Request) -> web.Response:
        return web.Response(text=f"ct:{state['ct']}")

    async def ct_set(request: web.Request) -> web.Response:
        state["ct"] = request.match_info["value"]
        return web.Response(text="ok")

    async def wifidata(request: web.Request) -> web.Response:
        return web.json_response(
            {"ssid": "TestNet", "mac": "AABBCCDDEEFF", "signal": "-60"}
        )

    app.router.add_get("/mypv_dev.jsn", mypv_dev)
    app.router.add_get("/monitorjson", monitor)
    app.router.add_get("/api/ct", ct_get)
    app.router.add_get("/api/ct={value}", ct_set)
    app.router.add_get("/api/wifidata.jsn", wifidata)
    return app


async def start_server(app: web.Application) -> str:
    """Start an aiohttp application on a random port and return its host."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return f"127.0.0.1:{port}"


async def _elwa2_server() -> str:
    return await start_server(
        make_device_app(
            ELWA2_SETUP,
            ELWA2_DATA,
            {"sn": "1601500000000000", "device": "AC ELWA 2", "fwversion": "e0002200"},
        )
    )


async def _acthor_server() -> str:
    return await start_server(
        make_device_app(
            ACTHOR_SETUP,
            ACTHOR_DATA,
            {
                "sn": "2001000000000000",
                "device": "AC-THOR",
                "fwversion": "a0020410",
                "number": 1,
            },
        )
    )


async def test_config_flow_user(hass: HomeAssistant) -> None:
    """Test the user config flow against a mock device."""
    host = await _elwa2_server()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": host}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "AC ELWA 2 0000000000"
    assert result["data"][CONF_DEVICE_TYPE] == DEVICE_TYPE_DEVICE


async def test_setup_and_entities(hass: HomeAssistant) -> None:
    """Test setting up the integration and creating entities."""
    host = await _elwa2_server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AC ELWA 2 0000000000",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_DEVICE},
        unique_id="1601500000000000",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get("sensor.my_pv_ac_elwa_2_temperature_1")
    assert state is not None, sorted(hass.states.async_entity_ids())
    assert state.state == "54.3"

    state = hass.states.get("sensor.my_pv_ac_elwa_2_heating_power")
    assert state is not None
    assert state.state == "3445.0"

    state = hass.states.get("water_heater.my_pv_ac_elwa_2")
    assert state is not None
    assert state.state == "electric"

    assert hass.states.get("number.my_pv_ac_elwa_2_target_temperature") is not None
    assert hass.states.get("select.my_pv_ac_elwa_2_boost_mode") is not None
    assert hass.states.get("switch.my_pv_ac_elwa_2_device_mode") is not None


async def test_meter_setup(hass: HomeAssistant) -> None:
    """Test setting up a WiFi Meter."""
    host = await start_server(make_meter_app())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="my-PV WiFi Meter 1234567890",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_METER},
        unique_id="1234567890",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert hass.states.get("sensor.my_pv_wifi_meter_power_l1") is not None
    assert hass.states.get("sensor.my_pv_wifi_meter_mains_frequency") is not None
    assert hass.states.get("number.my_pv_wifi_meter_ct_clamp_ratio") is not None


async def test_space_heating_climate_and_update(hass: HomeAssistant) -> None:
    """Test an AC THOR in space heating mode with a firmware update."""
    host = await _acthor_server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AC•THOR 0000000000",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_DEVICE},
        unique_id="2001000000000000",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    climate = hass.states.get("climate.my_pv_ac_thor")
    assert climate is not None, sorted(hass.states.async_entity_ids())
    assert climate.attributes["current_temperature"] == 41.2
    assert climate.attributes["temperature"] == 45.0

    update = hass.states.get("update.my_pv_ac_thor_firmware")
    assert update is not None
    assert update.state == "on"

    assert hass.states.get("switch.my_pv_ac_thor_legionella_mode") is None


async def test_advanced_option_exposes_settings(hass: HomeAssistant) -> None:
    """Test that the advanced option exposes additional entities."""
    host = await _acthor_server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AC•THOR 0000000000",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_DEVICE},
        options={CONF_ADVANCED: True},
        unique_id="2001000000000000",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.my_pv_ac_thor_legionella_mode") is not None
    assert (
        hass.states.get("number.my_pv_ac_thor_legionella_temperature") is not None
    )


async def test_diagnostics(hass: HomeAssistant) -> None:
    """Test the diagnostics output."""
    from custom_components.mypv_custom.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    host = await _acthor_server()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AC•THOR 0000000000",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_DEVICE},
        unique_id="2001000000000000",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["device"]["model"] == "AC•THOR"
    assert diag["values"]["data"]["power_act"] == 1234.0


async def test_service_calls(hass: HomeAssistant) -> None:
    """Test number, select, switch, button and water heater services."""
    app = make_device_app(
        ELWA2_SETUP,
        ELWA2_DATA,
        {"sn": "1601500000000000", "device": "AC ELWA 2", "fwversion": "e0002200"},
    )
    host = await start_server(app)
    state = app["state"]

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="AC ELWA 2 0000000000",
        data={"host": host, CONF_DEVICE_TYPE: DEVICE_TYPE_DEVICE},
        unique_id="1601500000000000",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.my_pv_ac_elwa_2_target_temperature", "value": 55},
        blocking=True,
    )
    assert float(state["setup"]["ww1target"]) == 550.0

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.my_pv_ac_elwa_2_boost_mode", "option": "1"},
        blocking=True,
    )
    assert int(state["setup"]["bstmode"]) == 1

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.my_pv_ac_elwa_2_device_mode"},
        blocking=True,
    )
    assert int(state["setup"]["devmode"]) == 0

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.my_pv_ac_elwa_2_reboot"},
        blocking=True,
    )
    assert int(state["setup"]["reboot_device"]) == 1

    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": "water_heater.my_pv_ac_elwa_2", "temperature": 60},
        blocking=True,
    )
    assert float(state["setup"]["ww1target"]) == 600.0


async def test_zeroconf_flow(hass: HomeAssistant) -> None:
    """Test the zeroconf discovery flow wiring."""
    device = AsyncMock()
    device.serial_number = "1601500000000000"
    device.model = "AC ELWA 2"
    device.disconnect = AsyncMock(return_value=True)

    info = ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname="my-pv-ac-elwa-2-1601500000000000.local.",
        name="my-pv-ac-elwa-2-1601500000000000._mypv._tcp.local.",
        port=443,
        type="_mypv._tcp.local.",
        properties={"": None},
    )

    with patch(
        "custom_components.mypv_custom.config_flow._probe_device",
        new=AsyncMock(return_value=(device, DEVICE_TYPE_DEVICE)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "zeroconf"}, data=info
        )

    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert result["title"] == "AC ELWA 2 0000000000"


async def test_dhcp_flow(hass: HomeAssistant) -> None:
    """Test the DHCP discovery flow wiring."""
    device = AsyncMock()
    device.serial_number = "2003000000000000"
    device.model = "AC•THOR 9s"
    device.disconnect = AsyncMock(return_value=True)

    info = DhcpServiceInfo(
        ip="127.0.0.1",
        macaddress="986d35cabcde",
        hostname="my-pv-ac-thor-9s.local.",
    )

    with patch(
        "custom_components.mypv_custom.config_flow._probe_device",
        new=AsyncMock(return_value=(device, DEVICE_TYPE_DEVICE)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "dhcp"}, data=info
        )

    assert result["type"] == "form"
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"
    assert result["title"] == "AC•THOR 9s 0000000000"
