"""HTTP(S) connection to a my-PV device.

The device exposes a small JSON API over its local network interface:

* ``GET /mypv_dev.jsn`` - static device information
* ``POST /auth.jsn`` with ``pw`` - authenticate (only when a password is set)
* ``GET /setup.jsn`` - configuration values, ``?<key>=<value>`` writes a value
* ``GET /data.jsn`` - live data values

Devices without a configured password are reached over plain HTTP on port 80,
devices with a password over HTTPS on port 443 with a self-signed certificate.

The embedded web server only accepts a couple of connections in a short burst
and then refuses new ones for about a second, so every request is retried with a
short backoff when the connection is refused.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager, suppress
from typing import Any, Final
from urllib.parse import urlencode, urlunsplit

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import (
    ClientConnectorCertificateError,
    ClientConnectorError,
    ClientError,
)

from .exceptions import (
    MyPVAuthenticationError,
    MyPVConnectionError,
    MyPVTooManyRequestsError,
)

_LOGGER = logging.getLogger(__name__)

HTTP_PORT: Final = 80
HTTPS_PORT: Final = 443

# Characters that should not be percent encoded in a query string.
_DONT_ENCODE: Final = "-_.!~*'()"

# The device refuses connections in bursts; retry with a backoff.
_CONNECTION_RETRIES: Final = 6
_CONNECTION_RETRY_DELAY: Final = 1.0


class _MyPVRequestCancelledError(Exception):
    """A request was superseded by a newer request for the same key."""


class MyPVConnection(ABC):
    """Base class for a connection to a my-PV device."""

    @abstractmethod
    async def open(self) -> bool:
        """Open the connection to the device."""

    @abstractmethod
    def is_open(self) -> bool:
        """Return True when the connection is open."""

    @abstractmethod
    async def close(self) -> bool:
        """Close the connection to the device."""

    @abstractmethod
    async def fetch_setup(self) -> dict[str, Any] | None:
        """Fetch the device setup."""

    @abstractmethod
    async def fetch_data(self) -> dict[str, Any] | None:
        """Fetch the device data."""

    @abstractmethod
    async def set_setup_value(
        self, key: str, value: Any, *, cancel: asyncio.Event | None = None
    ) -> dict[str, Any] | None:
        """Set a setup value."""

    @abstractmethod
    async def send_command(self, key: str, value: Any) -> bool:
        """Send a command to the device."""

    @property
    def uri(self) -> str | None:
        """Return the URI the connection is connected to."""
        return None

    def __str__(self) -> str:
        """Return a string representation of the connection."""
        return str(self.uri)


def _handle_rate_limiting[**P, T](
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Wait for the write lock and retry while the device is rate limiting."""

    @functools.wraps(func)
    async def wrapper(
        self: MyPVHTTPConnection,
        *args: Any,
        cancel: asyncio.Event | None = None,
        **kwargs: Any,
    ) -> T:
        async with self._write_request_lock():
            fails = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise _MyPVRequestCancelledError
                try:
                    return await func(self, *args, **kwargs)
                except MyPVTooManyRequestsError:
                    fails += 1
                    if fails >= 10:
                        raise
                    await asyncio.sleep(0.25)

    return wrapper


def _handle_reauthentication[**P, T](
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Re-authenticate once when the device lost the session."""

    @functools.wraps(func)
    async def wrapper(self: MyPVHTTPConnection, *args: Any, **kwargs: Any) -> T:
        try:
            return await func(self, *args, **kwargs)
        except MyPVAuthenticationError:
            if not self._session:
                raise
            await self._auth(self._session)
        return await func(self, *args, **kwargs)

    return wrapper


class MyPVHTTPConnection(MyPVConnection):
    """Connection to a my-PV device without authentication (plain HTTP)."""

    _PROTOCOL = "http"
    _SSL_CHECK = True
    _TIMEOUT: ClientTimeout | None = ClientTimeout(total=5, sock_connect=2)

    _host: str
    _session: ClientSession | None = None
    _owns_session: bool = True
    _connected: bool = False
    _headers: dict[str, str] | None = None
    _setup_url: str | None = None
    _data_url: str | None = None
    _mypv_dev: dict[str, Any] | None = None

    _lock: asyncio.Lock
    _waiting_requests: int = 0
    _waiting_write_requests: int = 0

    def __init__(self, host: str, *, session: ClientSession | None = None) -> None:
        """Initialize the connection.

        When a session is passed it is used for all requests and never closed by
        the connection, otherwise the connection creates and owns its session.
        """
        self._host = host
        self._session = session
        self._owns_session = session is None
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def _read_request_lock(self) -> AsyncIterator[None]:
        """Lock reads, fail fast when the device is already busy."""
        if self._waiting_requests >= 1:
            raise MyPVTooManyRequestsError("Request in progress")

        self._waiting_requests += 1
        try:
            await self._lock.acquire()
        finally:
            self._waiting_requests -= 1

        try:
            if self._waiting_write_requests:
                raise MyPVTooManyRequestsError("Write waiting")
            yield
        finally:
            self._lock.release()

    @asynccontextmanager
    async def _write_request_lock(self) -> AsyncIterator[None]:
        """Lock writes, which always wait for their turn."""
        self._waiting_requests += 1
        self._waiting_write_requests += 1
        try:
            await self._lock.acquire()
        finally:
            self._waiting_requests -= 1
            self._waiting_write_requests -= 1

        try:
            yield
        finally:
            self._lock.release()

    def _get_session(self) -> ClientSession:
        """Return the session to use, creating an owned one if needed."""
        if self._session is None or (self._owns_session and self._session.closed):
            self._session = ClientSession()
            self._owns_session = True
        return self._session

    def _request_kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments passed with every request."""
        kwargs: dict[str, Any] = {"ssl": self._SSL_CHECK}
        if self._TIMEOUT is not None:
            kwargs["timeout"] = self._TIMEOUT
        if self._headers:
            kwargs["headers"] = self._headers
        return kwargs

    async def _get_text(
        self, url: str, *, ssl: Any = None, data: Any = None
    ) -> tuple[int, str, str]:
        """Perform a GET request, retrying while the device refuses connections.

        Returns the status, content type and body text.
        """
        session = self._get_session()
        kwargs = self._request_kwargs()
        if ssl is not None:
            kwargs["ssl"] = ssl

        last_exc: ClientConnectorError | None = None
        for attempt in range(_CONNECTION_RETRIES):
            try:
                async with session.get(url, data=data, **kwargs) as response:
                    return response.status, response.content_type, await response.text()
            except ClientConnectorCertificateError:
                raise
            except ClientConnectorError as exc:
                if not isinstance(exc.os_error, ConnectionRefusedError):
                    raise MyPVConnectionError from exc
                last_exc = exc
                if attempt < _CONNECTION_RETRIES - 1:
                    _LOGGER.debug(
                        "Device refused connection, retrying in %ss",
                        _CONNECTION_RETRY_DELAY,
                    )
                    await asyncio.sleep(_CONNECTION_RETRY_DELAY)
            except (ClientError, TimeoutError) as exc:
                _LOGGER.debug(exc)
                await self.close()
                raise MyPVConnectionError from exc

        raise MyPVTooManyRequestsError from last_exc

    async def _post_text(
        self, url: str, data: str, *, ssl: Any = None
    ) -> tuple[int, str, str]:
        """Perform a POST request, retrying while the device refuses connections."""
        session = self._get_session()
        kwargs = self._request_kwargs()
        if ssl is not None:
            kwargs["ssl"] = ssl

        last_exc: ClientConnectorError | None = None
        for attempt in range(_CONNECTION_RETRIES):
            try:
                async with session.post(url, data=data, **kwargs) as response:
                    return response.status, response.content_type, await response.text()
            except ClientConnectorCertificateError:
                raise
            except ClientConnectorError as exc:
                if not isinstance(exc.os_error, ConnectionRefusedError):
                    raise MyPVConnectionError from exc
                last_exc = exc
                if attempt < _CONNECTION_RETRIES - 1:
                    await asyncio.sleep(_CONNECTION_RETRY_DELAY)
            except (ClientError, TimeoutError) as exc:
                _LOGGER.debug(exc)
                await self.close()
                raise MyPVConnectionError from exc

        raise MyPVTooManyRequestsError from last_exc

    async def _auth(self, session: ClientSession) -> bool:
        """Authenticate; the older HTTP only firmware does not support auth."""
        auth_url = urlunsplit([self._PROTOCOL, self._host, "/auth.jsn", None, None])

        _LOGGER.debug("GET %s", auth_url)

        try:
            status, _content_type, _body = await self._get_text(auth_url, ssl=True)
        except ClientConnectorCertificateError as exc:
            # The device redirects to SSL, so a password is required.
            raise MyPVAuthenticationError from exc

        if status == 429:
            raise MyPVTooManyRequestsError

        return True

    async def open(self) -> bool:
        """Open the connection to the device."""
        await self.close()

        mypv_dev_url = urlunsplit(
            [self._PROTOCOL, self._host, "/mypv_dev.jsn", None, None]
        )

        success = False
        try:
            session = self._get_session()
            status, content_type, body = await self._get_text(mypv_dev_url)
            response_json: dict[str, Any] = {}
            if content_type == "application/json":
                response_json = json.loads(body)

            if status != 200:
                _LOGGER.debug(
                    "Unexpected response %s: %s", status, body
                )
            else:
                self._mypv_dev = response_json

                if await self._auth(session):
                    self._setup_url = urlunsplit(
                        [self._PROTOCOL, self._host, "/setup.jsn", None, None]
                    )
                    self._data_url = urlunsplit(
                        [self._PROTOCOL, self._host, "/data.jsn", None, None]
                    )
                    success = True
        except json.JSONDecodeError:
            _LOGGER.debug("Invalid JSON response: %s", body)
        except MyPVConnectionError as exc:
            _LOGGER.debug(exc)
        finally:
            if success:
                self._connected = True
            else:
                await self.close()

        return success

    def is_open(self) -> bool:
        """Return True when the connection is open."""
        if not self._connected or self._session is None:
            return False
        return not self._session.closed

    async def close(self) -> bool:
        """Close the connection; an injected session is left open."""
        self._connected = False
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
        return True

    async def _get(
        self, url: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a GET request and return the parsed JSON body."""
        if (not self.is_open() and not await self.open()) or self._session is None:
            raise MyPVConnectionError

        if data:
            query = urlencode(data, safe=_DONT_ENCODE)
            url = f"{url}?{query}"

        _LOGGER.debug("GET %s", url)

        status, content_type, body = await self._get_text(url)

        if status == 429:
            raise MyPVTooManyRequestsError

        response_json: dict[str, Any] = {}
        if content_type == "application/json":
            try:
                response_json = json.loads(body)
            except json.JSONDecodeError as exc:
                _LOGGER.debug("Invalid JSON response: %s", body)
                raise MyPVConnectionError from exc

            if status == 200:
                return response_json

        if status == 401:
            raise MyPVAuthenticationError(response_json.get("msg"))

        _LOGGER.debug("Unexpected response %s: %s", status, body)
        return {}

    @property
    def mypv_dev(self) -> dict[str, Any] | None:
        """Return the ``/mypv_dev.jsn`` details."""
        return self._mypv_dev

    async def fetch_setup(self) -> dict[str, Any] | None:
        """Fetch the device setup."""
        if not self._setup_url:
            return None
        async with self._read_request_lock():
            return await self._get(self._setup_url)

    async def fetch_data(self) -> dict[str, Any] | None:
        """Fetch the device data."""
        if not self._data_url:
            return None
        async with self._read_request_lock():
            data = await self._get(self._data_url)
            return {key.lower(): value for key, value in data.items()}

    @_handle_rate_limiting
    async def set_setup_value(self, key: str, value: Any) -> dict[str, Any] | None:
        """Set a setup value."""
        if not self._setup_url:
            return None
        return await self._get(self._setup_url, {key: value})

    @_handle_rate_limiting
    async def send_command(self, key: str, value: Any) -> bool:
        """Send a command to the device."""
        if not self._setup_url:
            return False
        await self._get(self._setup_url, {key: value})
        return True

    @property
    def uri(self) -> str:
        """Return the URI the connection is connected to."""
        return urlunsplit([self._PROTOCOL, self._host, "/", None, None])


class MyPVHTTPSConnection(MyPVHTTPConnection):
    """Connection to a my-PV device with authentication (HTTPS)."""

    _PROTOCOL = "https"
    _SSL_CHECK = False

    _password: str

    def __init__(
        self, host: str, password: str, *, session: ClientSession | None = None
    ) -> None:
        """Initialize the connection."""
        super().__init__(host, session=session)
        self._password = password

    async def _auth(self, session: ClientSession) -> bool:
        """Authenticate against the device with the configured password."""
        auth_url = urlunsplit([self._PROTOCOL, self._host, "/auth.jsn", None, None])
        data = urlencode({"pw": self._password}, safe=_DONT_ENCODE)

        _LOGGER.debug("POST %s (password hidden)", auth_url)

        status, content_type, body = await self._post_text(auth_url, data)

        if status == 429:
            raise MyPVTooManyRequestsError

        if status == 200 and content_type == "application/json":
            if json.loads(body).get("auth", 0) == 1:
                return True
        else:
            _LOGGER.debug("Unexpected response %s: %s", status, body)

        raise MyPVAuthenticationError

    @_handle_reauthentication
    async def _get(
        self, url: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a GET request, re-authenticating once on failure."""
        return await super()._get(url, data)

    @_handle_reauthentication
    async def _post(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        """Perform a POST request, re-authenticating once on failure."""
        if (not self.is_open() and not await self.open()) or self._session is None:
            raise MyPVConnectionError

        encoded_data = urlencode(data, safe=_DONT_ENCODE)

        _LOGGER.debug("POST %s %s", url, encoded_data)

        status, content_type, body = await self._post_text(url, encoded_data)

        if status == 429:
            raise MyPVTooManyRequestsError

        response_json: dict[str, Any] = {}
        if content_type == "application/json":
            try:
                response_json = json.loads(body)
            except json.JSONDecodeError as exc:
                _LOGGER.debug("Invalid JSON response: %s", body)
                raise MyPVConnectionError from exc

            if status == 200:
                return response_json

        if status == 401:
            raise MyPVAuthenticationError(response_json.get("msg"))

        _LOGGER.debug("Unexpected response %s: %s", status, body)
        return {}

    @_handle_rate_limiting
    async def set_setup_value(self, key: str, value: Any) -> dict[str, Any] | None:
        """Set a setup value."""
        if not self._setup_url:
            return None
        return await self._post(self._setup_url, {key: value})

    @_handle_rate_limiting
    async def send_command(self, key: str, value: Any) -> bool:
        """Send a command to the device."""
        if not self._setup_url:
            return False
        await self._post(self._setup_url, {key: value})
        return True


class MyPVMeterConnection(MyPVHTTPConnection):
    """Connection to a my-PV WiFi Meter.

    The meter exposes a different API than the heating devices:

    * ``GET /monitorjson`` - per phase measurements
    * ``GET /api/wifidata.jsn`` - Wi-Fi and device information
    * ``GET /api/ct`` - current transformer ratio, ``GET /api/ct=<value>`` writes it
    * ``GET /api/restart?reset=<bool>`` - reboot
    """

    _PROTOCOL = "http"

    _wifidata: dict[str, Any] | None = None

    async def open(self) -> bool:
        """Open the connection to the meter."""
        await self.close()

        mypv_dev_url = urlunsplit(
            [self._PROTOCOL, self._host, "/mypv_dev.jsn", None, None]
        )

        success = False
        try:
            status, content_type, body = await self._get_text(mypv_dev_url)
            response_json: dict[str, Any] = {}
            if content_type == "application/json":
                response_json = json.loads(body)

            if status != 200:
                _LOGGER.debug("Unexpected response %s: %s", status, body)
            else:
                self._mypv_dev = response_json
                self._setup_url = urlunsplit(
                    [self._PROTOCOL, self._host, "/monitorjson", None, None]
                )
                self._data_url = self._setup_url
                success = True
        except json.JSONDecodeError:
            _LOGGER.debug("Invalid JSON response: %s", body)
        except MyPVConnectionError as exc:
            _LOGGER.debug(exc)
        finally:
            if success:
                self._connected = True
            else:
                await self.close()

        return success

    async def _auth(self, session: ClientSession) -> bool:
        """The meter does not require authentication."""
        return True

    @property
    def wifidata(self) -> dict[str, Any] | None:
        """Return the last ``/api/wifidata.jsn`` response."""
        return self._wifidata

    async def fetch_setup(self) -> dict[str, Any] | None:
        """Fetch the meter settings (CT ratio)."""
        if not self._data_url:
            return None
        ct_url = urlunsplit([self._PROTOCOL, self._host, "/api/ct", None, None])
        async with self._read_request_lock():
            _status, _content_type, text = await self._get_text(ct_url)
        ratio = None
        if "ct:" in text:
            with suppress(ValueError):
                ratio = float(text[text.index("ct:") + 3 :])
        return {"ct": ratio} if ratio is not None else {}

    async def fetch_data(self) -> dict[str, Any] | None:
        """Fetch the meter measurements and Wi-Fi information."""
        if not self._data_url:
            return None
        async with self._read_request_lock():
            data = await self._get(self._data_url)
            wifidata_url = urlunsplit(
                [self._PROTOCOL, self._host, "/api/wifidata.jsn", None, None]
            )
            with suppress(MyPVConnectionError, json.JSONDecodeError):
                _status, content_type, body = await self._get_text(wifidata_url)
                if content_type == "application/json":
                    self._wifidata = json.loads(body)

        values = _parse_monitor_json(data)
        if self._wifidata:
            with suppress(ValueError, TypeError):
                if (signal := self._wifidata.get("signal")) is not None:
                    values["wifi_signal_strength"] = float(signal)
            if (ssid := self._wifidata.get("ssid")) is not None:
                values["ssid"] = str(ssid)
        return values

    @_handle_rate_limiting
    async def set_setup_value(self, key: str, value: Any) -> dict[str, Any] | None:
        """Set a meter setting (only the CT ratio is supported)."""
        if key != "ct":
            return None
        ct_url = urlunsplit([self._PROTOCOL, self._host, f"/api/ct={value}", None, None])
        await self._get_text(ct_url)
        return {"ct": value}

    @_handle_rate_limiting
    async def send_command(self, key: str, value: Any = None) -> bool:
        """Send a command to the meter."""
        if key == "reboot_device":
            path = "/api/restart?reset=false"
        elif key == "factory_reset":
            path = "/api/restart?reset=true"
        else:
            return False
        url = urlunsplit([self._PROTOCOL, self._host, path, None, None])
        await self._get_text(url)
        return True


def _parse_monitor_json(data: dict[str, Any]) -> dict[str, Any]:
    """Convert the meter ``/monitorjson`` payload to flat data values."""
    phases = data.get("Datas") or {}
    values: dict[str, Any] = {}
    mapping = {
        "0": "l1",
        "1": "l2",
        "2": "l3",
    }
    for phase_key, suffix in mapping.items():
        phase = phases.get(phase_key)
        if not isinstance(phase, list) or len(phase) < 5:
            continue
        with suppress(ValueError, TypeError):
            values[f"volt_{suffix}"] = float(phase[0])
            values[f"curr_{suffix}"] = float(phase[1])
            values[f"power_{suffix}"] = float(phase[2])
            values[f"energy_supply_{suffix}"] = float(phase[3])
            values[f"energy_feed_{suffix}"] = float(phase[4])
            if len(phase) > 5:
                values[f"freq_{suffix}"] = float(phase[5])
    with suppress(ValueError, TypeError):
        if "freq_l1" in values:
            values["freq"] = values["freq_l1"]
    return values
