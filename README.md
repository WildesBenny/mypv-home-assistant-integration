# myPV (Custom) for Home Assistant

A fully local Home Assistant integration for [my-PV](https://www.my-pv.com)
devices, installable through HACS. It talks directly to the device on your local
network over its built-in HTTP(S) API. **No my-PV cloud is used.**

This integration is independent of the built-in `my_pv` integration and supports
every my-PV product the my-PV Setup app supports, including the WiFi Meter.

## Supported devices

| Product | Serial prefix | Notes |
| --- | --- | --- |
| SOL•THOR | `140100` | Solar thermal controller |
| AC ELWA 2 / AC ELWA 2 3 kW | `160150` `160151` `160152` | |
| AC ELWA-E | `16012` `16014` | Older device |
| ELWA | `1201` `120100` | DC immersion heater |
| AC•THOR / i / Viessmann / Greenheiss | `200100` `200103` `200110` `200113` `200120` | |
| AC•THOR 9s (+ Viessmann / Greenheiss / Tuxhorn) | `200300` `200310` `200320` `200330` | |
| HEA•THOR IoT 3,5 kW / 9 kW | `210300` `210900` | |
| my-PV WiFi Meter | 10-digit serial | Grid meter |

## Features

- Fully local polling of live data, setup values and commands.
- Automatic discovery through mDNS (`_mypv._tcp.local.`) and DHCP
  (OUI `98:6D:35`), plus manual setup by IP address.
- Optional password authentication (device key) for protected devices.
- Entities for every value the device exposes: sensors, numbers, selects,
  switches, buttons, a water heater or climate entity and a firmware update
  entity, depending on the product and its configured main mode.
- Optional advanced mode to expose network configuration, boost schedules,
  legionella mode and diagnostics.
- Diagnostics download with the password redacted.

## Installation

### HACS (recommended)

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/WildesBenny/mypv-home-assistant-integration`
   with category *Integration*.
2. Install **my-PV**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/mypv_custom` into your Home Assistant `config/custom_components`
directory and restart Home Assistant.

## Configuration

Most devices are discovered automatically and offered under
**Settings > Devices & services**. To add a device manually:

1. Go to **Settings > Devices & services > Add integration**.
2. Search for **myPV (Custom)**.
3. Enter the IP address or hostname of the device.
4. If the device uses a password, enter the device key. The device key can be
   found in the info menu of the device (or on the label of the HEA•THOR IoT).
   If no custom password is set, leave the password field empty.

The device is polled every 5 seconds. Setup values are refreshed every 6 polls
to reduce load on the device. When the device rate limits requests, the interval
is increased automatically.

### Advanced mode

Open the integration options and enable **Show advanced settings** to expose
network configuration, boost schedules, legionella mode and every other field
the device reports, including any value not covered by a dedicated entity. The
integration never drops a value the device returns; unknown fields appear as
diagnostic sensors in advanced mode. Reload the integration after changing the
option.

## Entities

The available entities depend on the device and its main mode:

- **Sensors**: temperatures, powers, voltages, currents, frequency, status,
  Wi-Fi signal, uptime, firmware versions and more.
- **Binary sensors**: boolean status values.
- **Numbers**: target temperatures, boost temperature, hysteresis, maximum
  power, CT clamp ratio (WiFi Meter).
- **Selects**: boost mode and other enumerations.
- **Switches**: device mode, boost mode, legionella mode and other booleans.
- **Buttons**: reboot, factory reset.
- **Water heater**: for hot water devices with a temperature sensor.
- **Climate**: for space heating devices with a temperature sensor.
- **Update**: firmware update with progress.

## Languages

The integration is fully localized. Entity names, enumeration states and the
configuration flow are available in:

- English
- German (Deutsch)
- Spanish (Español)
- French (Français)
- Italian (Italiano)
- Dutch (Nederlands)

## Troubleshooting

- Ensure Home Assistant and the device are on the same network and that the
  device is reachable (`http://<device>/mypv_dev.jsn`).
- If discovery does not work, check that your router does not block mDNS or
  broadcast traffic, then add the device manually by IP.
- If a password protected device reports an authentication error, re-enter the
  device key through the reauthentication flow.

## License

The local protocol implementation and product configuration are derived from the
official my-PV library, licensed under the Apache License 2.0
(Copyright my-PV GmbH). See [LICENSE](LICENSE).
