"""Tests for xmlrpc_extended.client and xmlrpc_extended.multiprocess."""

import os
import sys
import threading
import unittest
import xmlrpc.client
from unittest import mock

from xmlrpc_extended import ThreadPoolXMLRPCServer
from xmlrpc_extended.client import XMLRPCClient


def _start_server():
    server = ThreadPoolXMLRPCServer(
        ("127.0.0.1", 0),
        logRequests=False,
        allow_none=True,
    )
    server.register_function(lambda x: x + 1, "inc")
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return server, t, f"http://127.0.0.1:{server.server_address[1]}"


class XMLRPCClientTests(unittest.TestCase):
    """XMLRPCClient wraps ServerProxy with timeout and context management."""

    def setUp(self):
        # Arrange (shared): start a minimal server and build URL
        self.server, self.thread, self.url = _start_server()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_basic_call_succeeds(self):
        # Arrange
        # (server started in setUp)

        # Act
        with XMLRPCClient(self.url, timeout=5.0) as proxy:
            result = proxy.inc(1)

        # Assert
        self.assertEqual(2, result)

    def test_multiple_calls_in_context(self):
        # Arrange
        # (server started in setUp)

        # Act
        with XMLRPCClient(self.url, timeout=5.0) as proxy:
            first = proxy.inc(1)
            second = proxy.inc(10)

        # Assert
        self.assertEqual(2, first)
        self.assertEqual(11, second)

    def test_proxy_is_closed_on_exit(self):
        # Arrange
        client = XMLRPCClient(self.url, timeout=5.0)

        # Act
        with client as proxy:
            proxy.inc(1)

        # Assert: internal proxy was cleared after context exit
        self.assertIsNone(client._proxy)

    def test_default_timeout_is_30_seconds(self):
        # Arrange / Act
        client = XMLRPCClient(self.url)

        # Assert
        self.assertEqual(30.0, client._timeout)

    def test_allow_none_propagated(self):
        # Arrange / Act / Assert
        with XMLRPCClient(self.url, timeout=5.0, allow_none=True) as proxy:
            with self.assertRaises(xmlrpc.client.Fault):
                proxy.inc(None)

    def test_exit_when_proxy_is_none_is_a_noop(self):
        # Arrange: client that was never entered (proxy is None)
        client = XMLRPCClient(self.url)
        self.assertIsNone(client._proxy)

        # Act: calling __exit__ should not raise even with proxy=None
        client.__exit__(None, None, None)

        # Assert: proxy remains None and no error was raised
        self.assertIsNone(client._proxy)


class MultiprocessModuleTests(unittest.TestCase):
    """create_reuseport_socket raises on unsupported platforms."""

    def test_raises_on_non_linux(self):
        # Arrange: platform guard
        if sys.platform == "linux":
            self.skipTest("Running on Linux — SO_REUSEPORT is supported")
        from xmlrpc_extended.multiprocess import create_reuseport_socket

        # Act / Assert
        with self.assertRaises(OSError):
            create_reuseport_socket("127.0.0.1", 19999)

    def test_linux_creates_bound_socket(self):
        # Arrange: platform guard
        if sys.platform != "linux":
            self.skipTest("SO_REUSEPORT is Linux-only")
        import socket as _socket

        from xmlrpc_extended.multiprocess import create_reuseport_socket

        # Act
        sock = create_reuseport_socket("127.0.0.1", 0)

        # Assert
        try:
            self.assertEqual(_socket.AF_INET, sock.family)
            addr = sock.getsockname()
            self.assertEqual("127.0.0.1", addr[0])
            self.assertGreater(addr[1], 0)
        finally:
            sock.close()

    def test_raises_when_reuseport_not_supported_mocked(self):
        # Arrange: mock _is_reuseport_supported to return False (covers line 79)
        from xmlrpc_extended.multiprocess import create_reuseport_socket

        # Act / Assert
        with mock.patch("xmlrpc_extended.multiprocess._is_reuseport_supported", return_value=False):
            with self.assertRaises(OSError, msg="Should raise when SO_REUSEPORT is unavailable"):
                create_reuseport_socket("127.0.0.1", 0)

    def test_spawn_workers_returns_started_processes(self):
        # Arrange: platform guard
        if sys.platform != "linux":
            self.skipTest("spawn_workers uses SO_REUSEPORT — Linux only")
        from xmlrpc_extended.multiprocess import spawn_workers

        # Act
        processes = spawn_workers(os.getpid, num_workers=2)  # getpid is picklable

        # Assert
        try:
            for p in processes:
                p.join(timeout=3)
            self.assertEqual(2, len(processes))
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()

    def test_spawn_workers_defaults_to_cpu_count_when_num_workers_is_none(self):
        # Arrange: platform guard; covers multiprocess.py lines 117-119
        if sys.platform != "linux":
            self.skipTest("spawn_workers uses SO_REUSEPORT — Linux only")
        from xmlrpc_extended.multiprocess import spawn_workers

        # Act
        processes = spawn_workers(os.getpid, num_workers=None)

        # Assert: number of processes equals os.cpu_count() (or 1 if unavailable)
        expected = os.cpu_count() or 1
        try:
            for p in processes:
                p.join(timeout=3)
            self.assertEqual(expected, len(processes))
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()


if __name__ == "__main__":
    unittest.main()
