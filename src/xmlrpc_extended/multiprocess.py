"""Multi-process helpers for scale-out XML-RPC deployments (Linux only).

On Linux, ``SO_REUSEPORT`` allows multiple processes to bind to the same
address and port.  The kernel distributes incoming connections across all
listening processes, providing horizontal scale-out without a separate load
balancer.

Typical usage::

    # worker.py  — run this with: python worker.py &; python worker.py &
    import multiprocessing
    from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer
    from xmlrpc_extended.multiprocess import create_reuseport_socket

    def add(a, b):
        return a + b

    sock = create_reuseport_socket("0.0.0.0", 8000)
    server = ThreadPoolXMLRPCServer(
        ("0.0.0.0", 8000),
        max_workers=4,
        overload_policy=ServerOverloadPolicy.FAULT,
        bind_and_activate=False,
    )
    server.socket = sock
    server.server_bind = lambda: None  # already bound
    server.server_activate()
    server.register_function(add, "add")
    server.serve_forever()

.. note::

    ``SO_REUSEPORT`` is only available on Linux (kernel 3.9+). This module
    raises :class:`OSError` on non-Linux platforms.

.. warning::

    All worker processes sharing the socket must register identical methods.
    Sessions and shared mutable state are **not** safe across worker processes.
"""

from __future__ import annotations

import multiprocessing
import socket
import sys
from collections.abc import Callable


def _is_reuseport_supported() -> bool:
    return sys.platform == "linux" and hasattr(socket, "SO_REUSEPORT")


def create_reuseport_socket(
    host: str,
    port: int,
    *,
    backlog: int = 64,
) -> socket.socket:
    """Create a TCP socket with ``SO_REUSEPORT`` enabled.

    Multiple processes may call this function with the same *host* and *port*
    to share the listening socket.  Each call creates an independent socket
    file descriptor bound to the same address.

    Args:
        host: The interface address to bind to (e.g. ``"0.0.0.0"`` or
              ``"127.0.0.1"``).
        port: The TCP port to listen on.
        backlog: The OS-level accept backlog (default: 64).

    Returns:
        A bound, listening :class:`socket.socket`.

    Raises:
        OSError: If ``SO_REUSEPORT`` is not supported on the current platform.
    """
    if not _is_reuseport_supported():
        raise OSError("SO_REUSEPORT is not supported on this platform. Linux kernel 3.9+ is required.")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind((host, port))
    sock.listen(backlog)
    return sock


def spawn_workers(
    worker_fn: Callable[[], None],
    *,
    num_workers: int | None = None,
) -> list[multiprocessing.Process]:
    """Spawn *num_workers* worker processes, each running *worker_fn*.

    Args:
        worker_fn: A zero-argument callable that starts a server.  Each
            worker should call :func:`create_reuseport_socket` internally
            so they all share the same port.
        num_workers: Number of worker processes to start.  Defaults to the
            number of available CPU cores.

    Returns:
        List of started :class:`multiprocessing.Process` objects.  The caller
        is responsible for joining or terminating them.

    Example::

        processes = spawn_workers(run_my_server, num_workers=4)
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            for p in processes:
                p.terminate()
    """
    if num_workers is None:
        import os

        num_workers = os.cpu_count() or 1

    processes = []
    for _ in range(num_workers):
        p = multiprocessing.Process(target=worker_fn, daemon=False)
        p.start()
        processes.append(p)
    return processes


__all__ = ["create_reuseport_socket", "spawn_workers"]
