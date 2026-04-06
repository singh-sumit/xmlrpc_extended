"""Extended XML-RPC server primitives."""

from __future__ import annotations

import socket
import threading
import xmlrpc.client
from dataclasses import dataclass
from enum import Enum
from typing import Any
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from concurrent.futures import ThreadPoolExecutor


class ServerOverloadPolicy(str, Enum):
    """How the server reacts when no worker capacity is available."""

    BLOCK = "block"
    CLOSE = "close"
    FAULT = "fault"


@dataclass(frozen=True)
class XMLRPCServerConfig:
    """Configuration for :class:`ThreadPoolXMLRPCServer`."""

    max_workers: int = 8
    max_pending: int | None = None
    request_queue_size: int = 64
    overload_policy: ServerOverloadPolicy = ServerOverloadPolicy.BLOCK
    max_request_size: int = 1_048_576
    overload_fault_code: int = -32500
    overload_fault_string: str = "Server overloaded"


class LimitedXMLRPCRequestHandler(SimpleXMLRPCRequestHandler):
    """Request handler with a configurable maximum body size."""

    max_request_size = XMLRPCServerConfig.max_request_size

    def log_error(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib override
        """Only emit error log lines when the server has logging enabled."""
        if self.server.logRequests:
            super().log_error(format, *args)

    def do_POST(self) -> None:  # noqa: N802 - stdlib override keeps original name
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            self.send_error(501, "Chunked transfer encoding is not supported")
            return

        content_length = self.headers.get("content-length")
        if content_length is None:
            self.send_error(411, "Content-Length header is required")
            return

        try:
            request_size = int(content_length)
        except ValueError:
            request_size = None

        if request_size is None or request_size < 0:
            self.send_error(400, "Content-Length must be a valid non-negative integer")
            return

        if request_size > self.max_request_size:
            self.send_error(413, "XML-RPC request body too large")
            return

        super().do_POST()


class ThreadPoolXMLRPCServer(SimpleXMLRPCServer):
    """A drop-in XML-RPC server that dispatches requests through a thread pool.

    The constructor keeps stdlib parameter names such as ``requestHandler`` and
    ``logRequests`` for compatibility with :class:`SimpleXMLRPCServer`.
    """

    _config: XMLRPCServerConfig

    def __init__(
        self,
        addr: tuple[str, int],
        requestHandler: type[SimpleXMLRPCRequestHandler] = LimitedXMLRPCRequestHandler,
        logRequests: bool = True,  # noqa: N803 - stdlib compatibility
        allow_none: bool = False,
        encoding: str | None = None,
        bind_and_activate: bool = True,
        use_builtin_types: bool = False,
        *,
        max_workers: int = XMLRPCServerConfig.max_workers,
        max_pending: int | None = XMLRPCServerConfig.max_pending,
        request_queue_size: int = XMLRPCServerConfig.request_queue_size,
        overload_policy: ServerOverloadPolicy | str = ServerOverloadPolicy.BLOCK,
        max_request_size: int = XMLRPCServerConfig.max_request_size,
        overload_fault_code: int = XMLRPCServerConfig.overload_fault_code,
        overload_fault_string: str = XMLRPCServerConfig.overload_fault_string,
    ) -> None:
        normalized_policy = ServerOverloadPolicy(overload_policy)
        effective_pending = max_workers if max_pending is None else max_pending
        total_capacity = max_workers + effective_pending
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if effective_pending < 0:
            raise ValueError("max_pending must be at least 0")
        if request_queue_size < 1:
            raise ValueError("request_queue_size must be at least 1")
        if max_request_size < 1:
            raise ValueError("max_request_size must be at least 1")

        self.request_queue_size = request_queue_size
        self._config = XMLRPCServerConfig(
            max_workers=max_workers,
            max_pending=effective_pending,
            request_queue_size=request_queue_size,
            overload_policy=normalized_policy,
            max_request_size=max_request_size,
            overload_fault_code=overload_fault_code,
            overload_fault_string=overload_fault_string,
        )
        self._capacity = threading.Semaphore(total_capacity)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="xmlrpc")
        self._executor_lock = threading.Lock()
        self._executor_closed = False

        request_handler_class = self._build_request_handler(requestHandler, max_request_size)
        try:
            super().__init__(
                addr,
                requestHandler=request_handler_class,
                logRequests=logRequests,
                allow_none=allow_none,
                encoding=encoding,
                bind_and_activate=bind_and_activate,
                use_builtin_types=use_builtin_types,
            )
        except Exception:
            self.shutdown_executor(wait=False)
            raise

    @property
    def config(self) -> XMLRPCServerConfig:
        return self._config

    def process_request(self, request: Any, client_address: tuple[str, int]) -> None:
        if not self._acquire_capacity():
            self._reject_request(request)
            return

        try:
            self.submit_request(request, client_address)
        except RuntimeError:
            self._capacity.release()
            self.shutdown_request(request)
            raise

    def submit_request(self, request: Any, client_address: tuple[str, int]) -> None:
        """Submit a request to the worker pool."""

        self._executor.submit(self._process_request_worker, request, client_address)

    def _process_request_worker(self, request: Any, client_address: tuple[str, int]) -> None:
        try:
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except Exception:
            self.handle_error(request, client_address)
            self.shutdown_request(request)
        finally:
            self._capacity.release()

    def _acquire_capacity(self) -> bool:
        if self.config.overload_policy is ServerOverloadPolicy.BLOCK:
            self._capacity.acquire()
            return True
        return self._capacity.acquire(blocking=False)

    def _reject_request(self, request: Any) -> None:
        if self.config.overload_policy is ServerOverloadPolicy.FAULT:
            self._send_fault_response(request)
        self.shutdown_request(request)

    def _send_fault_response(self, request: Any) -> None:
        payload = xmlrpc.client.dumps(
            xmlrpc.client.Fault(
                self.config.overload_fault_code,
                self.config.overload_fault_string,
            ),
            methodresponse=True,
            allow_none=self.allow_none,
            encoding=self.encoding,
        )
        body = payload.encode(self.encoding or "utf-8")
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/xml\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + body
        try:
            request.sendall(response)
        except OSError:
            return
        # Half-close the write side so the client sees EOF and reads
        # the response, then drain remaining client data to prevent
        # BrokenPipeError when the client hasn't finished sending.
        try:
            request.shutdown(socket.SHUT_WR)
        except OSError:
            return
        try:
            request.settimeout(1.0)
            while request.recv(4096):
                pass
        except (OSError, TimeoutError):
            pass

    def shutdown_executor(self, *, wait: bool = True) -> None:
        with self._executor_lock:
            if self._executor_closed:
                return
            self._executor.shutdown(wait=wait, cancel_futures=False)
            self._executor_closed = True

    def server_close(self) -> None:
        self.shutdown_executor(wait=True)
        super().server_close()

    @staticmethod
    def _build_request_handler(
        request_handler: type[SimpleXMLRPCRequestHandler],
        max_request_size: int,
    ) -> type[SimpleXMLRPCRequestHandler]:
        if issubclass(request_handler, LimitedXMLRPCRequestHandler):
            return type(
                f"{request_handler.__name__}WithSizeLimit",
                (request_handler,),
                {"max_request_size": max_request_size},
            )
        return type(
            f"{request_handler.__name__}WithSizeLimit",
            (LimitedXMLRPCRequestHandler, request_handler),
            {"max_request_size": max_request_size},
        )


__all__ = [
    "LimitedXMLRPCRequestHandler",
    "ServerOverloadPolicy",
    "ThreadPoolXMLRPCServer",
    "XMLRPCServerConfig",
]
