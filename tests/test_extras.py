"""Tests for xmlrpc_extended.client and xmlrpc_extended.multiprocess."""

import sys
import threading
import unittest
import xmlrpc.client

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
        self.server, self.thread, self.url = _start_server()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_basic_call_succeeds(self):
        with XMLRPCClient(self.url, timeout=5.0) as proxy:
            self.assertEqual(2, proxy.inc(1))

    def test_multiple_calls_in_context(self):
        with XMLRPCClient(self.url, timeout=5.0) as proxy:
            self.assertEqual(2, proxy.inc(1))
            self.assertEqual(11, proxy.inc(10))

    def test_proxy_is_closed_on_exit(self):
        client = XMLRPCClient(self.url, timeout=5.0)
        with client as proxy:
            proxy.inc(1)
        # After exit the internal proxy should be cleared
        self.assertIsNone(client._proxy)

    def test_default_timeout_is_30_seconds(self):
        client = XMLRPCClient(self.url)
        self.assertEqual(30.0, client._timeout)

    def test_allow_none_propagated(self):
        with XMLRPCClient(self.url, timeout=5.0, allow_none=True) as proxy:
            # calling inc with None should raise a fault, not a connection error
            with self.assertRaises(xmlrpc.client.Fault):
                proxy.inc(None)


class MultiprocessModuleTests(unittest.TestCase):
    """create_reuseport_socket raises on unsupported platforms."""

    def test_raises_on_non_linux(self):
        if sys.platform == "linux":
            self.skipTest("Running on Linux — SO_REUSEPORT is supported")
        from xmlrpc_extended.multiprocess import create_reuseport_socket

        with self.assertRaises(OSError):
            create_reuseport_socket("127.0.0.1", 19999)

    def test_linux_creates_bound_socket(self):
        if sys.platform != "linux":
            self.skipTest("SO_REUSEPORT is Linux-only")
        import socket as _socket

        from xmlrpc_extended.multiprocess import create_reuseport_socket

        sock = create_reuseport_socket("127.0.0.1", 0)
        try:
            self.assertEqual(_socket.AF_INET, sock.family)
            addr = sock.getsockname()
            self.assertEqual("127.0.0.1", addr[0])
            self.assertGreater(addr[1], 0)
        finally:
            sock.close()

    def test_spawn_workers_returns_started_processes(self):
        if sys.platform != "linux":
            self.skipTest("spawn_workers uses SO_REUSEPORT — Linux only")
        # spawn_workers requires a picklable top-level callable; verify its
        # return type and number of processes without actually running a server.
        import os

        from xmlrpc_extended.multiprocess import spawn_workers

        processes = spawn_workers(os.getpid, num_workers=2)  # getpid is picklable
        try:
            for p in processes:
                p.join(timeout=3)
            self.assertEqual(2, len(processes))
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()


if __name__ == "__main__":
    unittest.main()
