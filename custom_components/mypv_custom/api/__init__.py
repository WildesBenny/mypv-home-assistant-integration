"""Local my-PV protocol implementation.

The protocol and product configuration are vendored from the official my-PV
library (Apache-2.0, Copyright my-PV GmbH) and extended with the WiFi Meter.
"""

from .connection import (
    MyPVConnection,
    MyPVHTTPConnection,
    MyPVHTTPSConnection,
    MyPVMeterConnection,
)
from .device import MyPVDevice, MyPVDeviceMainMode, MyPVLocalDevice
from .exceptions import (
    MyPVAuthenticationError,
    MyPVConnectionError,
    MyPVDeviceNotSupportedError,
    MyPVException,
    MyPVNotSupportedError,
    MyPVTooManyRequestsError,
)
from .meter import MyPVMeterDevice

__all__ = [
    "MyPVAuthenticationError",
    "MyPVConnection",
    "MyPVConnectionError",
    "MyPVDevice",
    "MyPVDeviceMainMode",
    "MyPVDeviceNotSupportedError",
    "MyPVException",
    "MyPVHTTPConnection",
    "MyPVHTTPSConnection",
    "MyPVLocalDevice",
    "MyPVMeterConnection",
    "MyPVMeterDevice",
    "MyPVNotSupportedError",
    "MyPVTooManyRequestsError",
]
