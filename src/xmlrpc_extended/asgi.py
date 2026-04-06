"""ASGI adapter for XML-RPC services.

Provides :class:`XMLRPCASGIApp`, a compliant **ASGI 3** application that
exposes registered XML-RPC methods over HTTP using the asynchronous server
gateway interface — compatible with any ASGI server (uvicorn, hypercorn,
granian, daphne, …).

Design principles
-----------------
- **Zero runtime dependencies** — pure stdlib + :mod:`asyncio`.
- **Drop-in method registry** — inherits
  :class:`xmlrpc.server.SimpleXMLRPCDispatcher` so the familiar
  ``register_function`` / ``register_instance`` / ``register_introspection_functions``
  API works unchanged.
- **Async-first** — ``async def`` handler functions are awaited directly in the
  event loop; synchronous handlers run in a thread pool via
  :func:`asyncio.to_thread` and never block the event loop.
- **ASGI lifespan** — startup/shutdown events cleanly drain the thread pool.

Typical usage
-------------
::

    # app.py
    from xmlrpc_extended.asgi import XMLRPCASGIApp

    async def fetch_data(key: str) -> dict:
        \"\"\"Async handler — runs directly in the event loop.\"\"\"
        return {"key": key, "value": 42}

    def compute(a: int, b: int) -> int:
        \"\"\"Sync handler — runs in a thread pool automatically.\"\"\"
        return a + b

    app = XMLRPCASGIApp(rpc_path="/rpc", max_workers=4)
    app.register_function(fetch_data, "fetch_data")
    app.register_function(compute, "compute")

    # Run with any ASGI server:
    #   uvicorn app:app --host 0.0.0.0 --port 8000
    #   hypercorn app:app
    #   granian --interface asgi app:app

Call it from a client::

    from xmlrpc_extended.client import XMLRPCClient

    with XMLRPCClient("http://127.0.0.1:8000/rpc", timeout=5.0) as proxy:
        result = proxy.compute(6, 7)   # → 42

.. note::
    This module requires Python 3.10+ (same as the rest of the package) and
    makes use of :func:`asyncio.to_thread` which was added in Python 3.9.

.. warning::
    Do **not** enable ``allow_dotted_names=True`` — it bypasses security
    checks and can expose internal object attributes as callable methods.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import xmlrpc.client
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from xmlrpc.server import SimpleXMLRPCDispatcher, resolve_dotted_attribute

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ASGI type aliases (no third-party typing package required)
# ---------------------------------------------------------------------------

_ASGIScope = dict[str, Any]
_ASGIMessage = dict[str, Any]
_ASGIReceive = Callable[[], Any]
_ASGISend = Callable[[_ASGIMessage], Any]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MAX_REQUEST_SIZE: int = 1_048_576  # 1 MiB
_DEFAULT_RPC_PATH: str = "/"
_DEFAULT_MAX_WORKERS: int = 4


class XMLRPCASGIApp(SimpleXMLRPCDispatcher):
    """ASGI 3-compliant XML-RPC application.

    Inherits :class:`~xmlrpc.server.SimpleXMLRPCDispatcher` for full
    compatibility with the standard registration API.  Both ``async def``
    and regular synchronous handler functions are supported.

    Args:
        max_workers: Thread-pool size for synchronous handler functions.
            ``async def`` handlers bypass the pool entirely.
        max_request_size: Maximum accepted request body in bytes.
            Requests larger than this receive ``413 Payload Too Large``.
        rpc_path: URL path at which XML-RPC ``POST`` requests are accepted.
            Requests to any other path receive ``404 Not Found``.
        allow_none: Whether ``None`` values are permitted in XML-RPC payloads.
        encoding: XML encoding override; ``None`` defaults to UTF-8.
        use_builtin_types: Map XML-RPC ``dateTime``/``base64`` to Python
            built-in :class:`datetime.datetime` / :class:`bytes`.

    Example:
        ```python
        app = XMLRPCASGIApp(rpc_path="/rpc", max_workers=4)
        app.register_function(lambda a, b: a + b, "add")

        # Run with: uvicorn mymodule:app
        ```
    """

    def __init__(
        self,
        *,
        max_workers: int = _DEFAULT_MAX_WORKERS,
        max_request_size: int = _DEFAULT_MAX_REQUEST_SIZE,
        rpc_path: str = _DEFAULT_RPC_PATH,
        allow_none: bool = False,
        encoding: str | None = None,
        use_builtin_types: bool = False,
    ) -> None:
        """Initialise the ASGI application.

        Args:
            max_workers: Thread-pool size for synchronous handler functions.
            max_request_size: Maximum body in bytes (default 1 MiB).
            rpc_path: URL path accepted for XML-RPC POST requests.
            allow_none: Allow ``None`` in XML-RPC payloads.
            encoding: XML encoding; ``None`` uses UTF-8.
            use_builtin_types: Map XML types to Python built-ins.

        Raises:
            ValueError: If ``max_workers < 1`` or ``max_request_size < 1``.
        """
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_request_size < 1:
            raise ValueError("max_request_size must be at least 1")

        super().__init__(allow_none=allow_none, encoding=encoding, use_builtin_types=use_builtin_types)
        self._max_request_size = max_request_size
        self._rpc_path = rpc_path
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None

    # ------------------------------------------------------------------
    # ASGI entry point
    # ------------------------------------------------------------------

    async def __call__(
        self,
        scope: _ASGIScope,
        receive: _ASGIReceive,
        send: _ASGISend,
    ) -> None:
        """ASGI 3 callable entry point.

        Dispatches to :meth:`_handle_lifespan` for ``lifespan`` scopes and
        :meth:`_handle_http` for ``http`` scopes.  Other scope types are
        silently ignored to stay forward-compatible with future ASGI extensions.

        Args:
            scope: ASGI connection scope dict.
            receive: Async callable that yields incoming ASGI events.
            send: Async callable for sending ASGI response events.
        """
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(scope, receive, send)
        elif scope_type == "http":
            await self._handle_http(scope, receive, send)
        # Other scope types (websocket, etc.) are silently ignored.

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    async def _handle_lifespan(
        self,
        scope: _ASGIScope,
        receive: _ASGIReceive,
        send: _ASGISend,
    ) -> None:
        """Handle ASGI lifespan startup and shutdown events."""
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="xmlrpc-asgi",
                )
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                if self._executor is not None:
                    self._executor.shutdown(wait=True)
                    self._executor = None
                await send({"type": "lifespan.shutdown.complete"})
                return

    # ------------------------------------------------------------------
    # HTTP request handling
    # ------------------------------------------------------------------

    async def _handle_http(
        self,
        scope: _ASGIScope,
        receive: _ASGIReceive,
        send: _ASGISend,
    ) -> None:
        """Handle an HTTP request scope."""
        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()

        if path != self._rpc_path:
            await self._send_http_response(send, 404, b"Not Found")
            return

        if method != "POST":
            await self._send_http_response(
                send,
                405,
                b"Method Not Allowed",
                extra_headers=[(b"allow", b"POST")],
            )
            return

        body = await self._read_body(receive)

        if len(body) > self._max_request_size:
            await self._send_http_response(send, 413, b"Payload Too Large")
            return

        response_xml = await self._async_marshaled_dispatch(body)

        await self._send_http_response(
            send,
            200,
            response_xml,
            content_type=b"text/xml; charset=utf-8",
        )

    async def _read_body(self, receive: _ASGIReceive) -> bytes:
        """Read and concatenate all body chunks from the ASGI receive channel.

        Args:
            receive: The ASGI receive callable.

        Returns:
            The complete request body as bytes.
        """
        chunks: list[bytes] = []
        while True:
            event = await receive()
            body_chunk = event.get("body", b"")
            if body_chunk:
                chunks.append(body_chunk)
            if not event.get("more_body", False):
                break
        return b"".join(chunks)

    # ------------------------------------------------------------------
    # Async dispatch
    # ------------------------------------------------------------------

    async def _async_marshaled_dispatch(self, data: bytes) -> bytes:
        """Parse, dispatch, and marshal an XML-RPC request asynchronously.

        Args:
            data: Raw XML-RPC request body bytes.

        Returns:
            Encoded XML-RPC response bytes (always a valid XML-RPC response,
            including fault responses for invalid or unsupported calls).
        """
        encoding = self.encoding or "utf-8"
        try:
            params, method = xmlrpc.client.loads(data, use_builtin_types=self.use_builtin_types)
        except Exception as exc:
            fault = xmlrpc.client.Fault(-32700, f"Parse error: {exc}")
            return xmlrpc.client.dumps(
                fault,
                allow_none=self.allow_none,
                encoding=encoding,
            ).encode(encoding, "xmlcharrefreplace")

        try:
            result = await self._async_dispatch(str(method), tuple(params))
            response = xmlrpc.client.dumps(
                (result,),
                methodresponse=True,
                allow_none=self.allow_none,
                encoding=encoding,
            )
        except xmlrpc.client.Fault as fault:
            response = xmlrpc.client.dumps(
                fault,
                allow_none=self.allow_none,
                encoding=encoding,
            )
        except Exception as exc:
            response = xmlrpc.client.dumps(
                xmlrpc.client.Fault(1, f"{type(exc).__name__}: {exc}"),
                allow_none=self.allow_none,
                encoding=encoding,
            )

        return response.encode(encoding, "xmlcharrefreplace")

    async def _async_dispatch(self, method: str, params: tuple[Any, ...]) -> Any:
        """Dispatch a parsed XML-RPC call, supporting both sync and async handlers.

        Registered ``async def`` functions are awaited directly.  Registered
        sync functions are dispatched to the thread pool via
        :func:`asyncio.to_thread`.  Instance ``_dispatch`` hooks are supported
        in both flavours.

        Args:
            method: The XML-RPC method name.
            params: Positional parameters from the XML-RPC call.

        Returns:
            The return value from the handler.

        Raises:
            xmlrpc.client.Fault: If the method is not found.
            Exception: Re-raised from the handler (converted to a fault by
                :meth:`_async_marshaled_dispatch`).
        """
        func: Callable[..., Any] | None = self.funcs.get(method)

        if func is None:
            if self.instance is not None:
                if hasattr(self.instance, "_dispatch"):
                    dispatch_fn = self.instance._dispatch
                    if inspect.iscoroutinefunction(dispatch_fn):
                        return await dispatch_fn(method, params)
                    return await asyncio.to_thread(dispatch_fn, method, params)
                # Resolve dotted attribute from instance
                allow_dotted = getattr(self, "allow_dotted_names", False)
                try:
                    func = resolve_dotted_attribute(
                        self.instance,
                        method,
                        allow_dotted,
                    )
                except AttributeError:
                    pass

        if func is None:
            raise xmlrpc.client.Fault(-32601, f'Method "{method}" is not supported')

        if inspect.iscoroutinefunction(func):
            return await func(*params)

        # Get or lazily create the thread pool for sync handlers.
        executor = self._get_executor()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, lambda: func(*params))

    def _get_executor(self) -> ThreadPoolExecutor:
        """Return the active thread pool, creating one lazily if not yet started.

        This supports the common pattern of calling the app without going
        through the ASGI lifespan protocol (e.g. in tests with
        :class:`httpx.ASGITransport`).

        Returns:
            The :class:`~concurrent.futures.ThreadPoolExecutor` for sync handlers.
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="xmlrpc-asgi",
            )
        return self._executor

    def close(self) -> None:
        """Shut down the thread pool gracefully.

        Called automatically during the ASGI lifespan shutdown event.  Call
        this explicitly when using the app outside of a lifespan-aware ASGI
        server (e.g. in tests).
        """
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    # ------------------------------------------------------------------
    # HTTP response helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _send_http_response(
        send: _ASGISend,
        status: int,
        body: bytes,
        content_type: bytes = b"text/plain; charset=utf-8",
        extra_headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        """Send a complete HTTP response through the ASGI send callable.

        Args:
            send: ASGI send callable.
            status: HTTP status code.
            body: Response body bytes.
            content_type: ``Content-Type`` header value.
            extra_headers: Additional ``(name, value)`` header tuples.
        """
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", content_type),
            (b"content-length", str(len(body)).encode()),
        ]
        if extra_headers:
            headers.extend(extra_headers)

        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["XMLRPCASGIApp"]
