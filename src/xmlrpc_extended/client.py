"""Optional XML-RPC client helpers.

Provides :class:`XMLRPCClient`, a context-manager wrapper around
:class:`xmlrpc.client.ServerProxy` with an explicit connection timeout.

Usage::

    from xmlrpc_extended.client import XMLRPCClient

    with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
        result = proxy.add(1, 2)
"""

from __future__ import annotations

import http.client
import xmlrpc.client
from typing import Any


class _TimeoutTransport(xmlrpc.client.Transport):
    """An HTTP transport that enforces a per-connection timeout."""

    def __init__(
        self,
        timeout: float,
        use_datetime: bool = False,
        use_builtin_types: bool = False,
    ) -> None:
        super().__init__(use_datetime=use_datetime, use_builtin_types=use_builtin_types)
        self._timeout = timeout

    def make_connection(self, host: Any) -> http.client.HTTPConnection:
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class XMLRPCClient:
    """Context-manager wrapper for :class:`~xmlrpc.client.ServerProxy`.

    Ensures the underlying connection is closed on exit and enforces an
    explicit connection timeout so hung servers do not block callers
    indefinitely.

    Args:
        uri: Full URL of the XML-RPC endpoint, e.g. ``"http://127.0.0.1:8000/"``.
        timeout: Socket timeout in seconds (default: 30.0).
        allow_none: Whether ``None`` values are permitted in payloads.
        use_builtin_types: Use Python built-in types for XML-RPC date/binary.

    Example::

        with XMLRPCClient("http://127.0.0.1:8000/", timeout=5.0) as proxy:
            result = proxy.my_method(arg1, arg2)

    .. note::
        Retrying failed requests is the caller's responsibility.  XML-RPC
        methods are not necessarily idempotent, so automatic retries would
        risk duplicate side-effects.  Wrap the ``with`` block in your own
        retry loop when retrying is safe.
    """

    def __init__(
        self,
        uri: str,
        *,
        timeout: float = 30.0,
        allow_none: bool = False,
        use_builtin_types: bool = False,
    ) -> None:
        self._uri = uri
        self._timeout = timeout
        self._allow_none = allow_none
        self._use_builtin_types = use_builtin_types
        self._proxy: xmlrpc.client.ServerProxy | None = None

    def __enter__(self) -> xmlrpc.client.ServerProxy:
        transport = _TimeoutTransport(
            self._timeout,
            use_builtin_types=self._use_builtin_types,
        )
        self._proxy = xmlrpc.client.ServerProxy(
            self._uri,
            transport=transport,
            allow_none=self._allow_none,
        )
        return self._proxy

    def __exit__(self, *_: object) -> None:
        if self._proxy is not None:
            # ServerProxy supports __exit__ since Python 3.10 (our minimum version).
            # Calling it via type() avoids the __getattr__ XML-RPC dispatch path.
            type(self._proxy).__exit__(self._proxy, None, None, None)
            self._proxy = None


__all__ = ["XMLRPCClient"]
