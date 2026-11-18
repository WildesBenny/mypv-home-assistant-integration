"""Constants for the my-PV integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "mypv_custom"

MANUFACTURER: Final = "my-PV"

# How often the device is polled for new data.
UPDATE_INTERVAL: Final = timedelta(seconds=5)

# Option key to expose advanced (network and schedule) settings.
CONF_ADVANCED: Final = "advanced"

# Config entry data key holding the detected device type.
CONF_DEVICE_TYPE: Final = "device_type"
DEVICE_TYPE_DEVICE: Final = "device"
DEVICE_TYPE_METER: Final = "meter"

# Serial number length of the WiFi Meter.
METER_SERIAL_LENGTH: Final = 10
