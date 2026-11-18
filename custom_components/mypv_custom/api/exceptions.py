"""Exceptions for the my-PV local API."""


class MyPVException(Exception):
    """Base my-PV exception."""


class MyPVConnectionError(MyPVException):
    """Raised when the device cannot be reached."""


class MyPVTooManyRequestsError(MyPVConnectionError):
    """Raised when the device rate limits requests."""


class MyPVAuthenticationError(MyPVException):
    """Raised when authentication fails."""


class MyPVNotSupportedError(MyPVException):
    """Raised when a value or command is not supported by the device."""


class MyPVDeviceNotSupportedError(MyPVNotSupportedError):
    """Raised when a device model is not supported."""
