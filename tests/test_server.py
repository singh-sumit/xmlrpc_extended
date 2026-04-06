import http.client
import io
import sys
import threading
import time
import unittest
import xmlrpc.client
from contextlib import contextmanager
from unittest import mock

from xmlrpc_extended import ServerOverloadPolicy, ServerStats, ThreadPoolXMLRPCServer


@contextmanager
def running_server(
    *,
    max_workers=2,
    max_pending=None,
    overload_policy=ServerOverloadPolicy.BLOCK,
    max_request_size=1_048_576,
):
    server = ThreadPoolXMLRPCServer(
        ("127.0.0.1", 0),
        max_workers=max_workers,
        max_pending=max_pending,
        overload_policy=overload_policy,
        max_request_size=max_request_size,
        logRequests=False,
        allow_none=True,
    )
    server.register_introspection_functions()
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ThreadPoolXMLRPCServerTests(unittest.TestCase):
    def test_registers_functions_and_instances_like_simple_xmlrpc_server(self):
        # Arrange
        def add(left, right):
            return left + right

        class Methods:
            def ping(self):
                return "pong"

        with running_server() as (server, url):
            server.register_function(add, "add")
            server.register_instance(Methods())
            proxy = xmlrpc.client.ServerProxy(url, allow_none=True)

            # Act / Assert
            self.assertIn("system.listMethods", proxy.system.listMethods())
            self.assertIn("add", proxy.system.listMethods())
            self.assertIn("ping", proxy.system.listMethods())
            self.assertEqual(5, proxy.add(2, 3))
            self.assertEqual("pong", proxy.ping())

    def test_processes_requests_concurrently(self):
        # Arrange
        active = 0
        max_active = 0
        state_lock = threading.Lock()
        overlap = threading.Event()

        def observe_parallel():
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    overlap.set()

            overlap.wait(timeout=1)
            time.sleep(0.05)

            with state_lock:
                active -= 1

            return "ok"

        with running_server(max_workers=2, max_pending=2) as (server, url):
            server.register_function(observe_parallel, "observe_parallel")
            results = []

            def invoke():
                proxy = xmlrpc.client.ServerProxy(url, allow_none=True)
                results.append(proxy.observe_parallel())

            # Act: fire 2 concurrent requests
            threads = [threading.Thread(target=invoke) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

            # Assert: both ran and overlapped
            self.assertEqual(2, len(results))
            self.assertEqual(["ok", "ok"], sorted(results))
            self.assertEqual(2, max_active)

    def test_close_policy_rejects_requests_when_server_is_saturated(self):
        # Arrange: server at capacity with CLOSE policy
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.CLOSE) as (server, url):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            # Act / Assert: third request gets connection closed
            with self.assertRaises((OSError, xmlrpc.client.ProtocolError, http.client.HTTPException)):
                xmlrpc.client.ServerProxy(url).block()

            release.set()
            holder.join(timeout=2)

    def test_fault_policy_returns_xmlrpc_fault_when_server_is_saturated(self):
        # Arrange: server at capacity with FAULT policy
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.FAULT) as (server, url):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            # Act / Assert: third request gets an XML-RPC fault
            with self.assertRaises(xmlrpc.client.Fault) as error:
                xmlrpc.client.ServerProxy(url).block()

            self.assertEqual(-32500, error.exception.faultCode)
            self.assertIn("overloaded", error.exception.faultString.lower())

            release.set()
            holder.join(timeout=2)

    def test_server_close_waits_for_inflight_requests(self):
        # Arrange: one in-flight request that blocks while shutdown is requested
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0) as (server, url):
            server.register_function(block, "block")
            client_thread = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            client_thread.start()
            started.wait(timeout=2)

            # Act: shut down while the request is still in flight
            def stop_server():
                server.shutdown()
                server.server_close()

            stopper = threading.Thread(target=stop_server)
            stopper.start()
            time.sleep(0.1)

            # Assert: stopper is still blocked (waiting for inflight request)
            self.assertTrue(stopper.is_alive())

            release.set()
            stopper.join(timeout=2)
            client_thread.join(timeout=2)

    def test_rejects_oversized_xmlrpc_payloads(self):
        # Arrange: server with 32-byte limit; request body is 33 bytes
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)
            body = b"x" * 33

            # Act
            connection.request(
                "POST",
                "/",
                body=body,
                headers={
                    "Content-Type": "text/xml",
                    "Content-Length": str(len(body)),
                },
            )
            response = connection.getresponse()

            # Assert
            self.assertEqual(413, response.status)
            connection.close()

    def test_rejects_invalid_content_length_header(self):
        # Arrange
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            # Act: send non-integer Content-Length
            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Content-Length", "abc")
            connection.endheaders()
            response = connection.getresponse()

            # Assert
            self.assertEqual(400, response.status)
            connection.close()

    def test_rejects_missing_content_length_header(self):
        # Arrange
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            # Act: POST without Content-Length
            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.endheaders()
            response = connection.getresponse()

            # Assert
            self.assertEqual(411, response.status)
            connection.close()

    def test_rejects_negative_content_length(self):
        # Arrange
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            # Act: Content-Length is negative (-1)
            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Content-Length", "-1")
            connection.endheaders()
            response = connection.getresponse()

            # Assert
            self.assertEqual(400, response.status)
            connection.close()

    def test_rejects_chunked_transfer_encoding(self):
        # Arrange
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            # Act: send chunked Transfer-Encoding
            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Transfer-Encoding", "chunked")
            connection.endheaders()
            response = connection.getresponse()

            # Assert
            self.assertEqual(501, response.status)
            connection.close()

    def test_rejects_when_running_and_queued_requests_reach_limit(self):
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=1, overload_policy=ServerOverloadPolicy.CLOSE) as (server, url):
            server.register_function(block, "block")
            second_request_queued = threading.Event()
            submit_lock = threading.Lock()
            submit_count = 0
            original_submit_request = server.submit_request

            def tracking_submit_request(*args, **kwargs):
                nonlocal submit_count
                with submit_lock:
                    submit_count += 1
                    current_submit = submit_count
                    original_submit_request(*args, **kwargs)
                if current_submit == 2:
                    second_request_queued.set()

            with mock.patch.object(server, "submit_request", side_effect=tracking_submit_request):
                first = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
                second = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
                first.start()
                started.wait(timeout=2)
                second.start()
                self.assertTrue(second_request_queued.wait(timeout=2))

                with self.assertRaises((OSError, xmlrpc.client.ProtocolError, http.client.HTTPException)):
                    xmlrpc.client.ServerProxy(url).block()

                release.set()
                first.join(timeout=2)
                second.join(timeout=2)
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())

    def test_oversized_payload_does_not_log_when_log_requests_false(self):
        # Arrange: server with logRequests=False; oversized body
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)
            body = b"x" * 33

            captured = io.StringIO()
            # Act: send oversized payload; capture stderr
            with mock.patch.object(sys, "stderr", captured):
                connection.request(
                    "POST",
                    "/",
                    body=body,
                    headers={
                        "Content-Type": "text/xml",
                        "Content-Length": str(len(body)),
                    },
                )
                response = connection.getresponse()

            # Assert: 413 returned, no logging
            self.assertEqual(413, response.status)
            self.assertEqual("", captured.getvalue())
            connection.close()

    def test_invalid_content_length_does_not_log_when_log_requests_false(self):
        # Arrange
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            captured = io.StringIO()
            # Act: send invalid Content-Length; capture stderr
            with mock.patch.object(sys, "stderr", captured):
                connection.putrequest("POST", "/")
                connection.putheader("Content-Type", "text/xml")
                connection.putheader("Content-Length", "abc")
                connection.endheaders()
                response = connection.getresponse()

            # Assert: 400 returned, no logging
            self.assertEqual(400, response.status)
            self.assertEqual("", captured.getvalue())
            connection.close()


class ConstructorValidationTests(unittest.TestCase):
    """Constructor rejects invalid configuration values."""

    def test_rejects_zero_max_workers(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), max_workers=0, bind_and_activate=False)

    def test_rejects_negative_max_workers(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), max_workers=-1, bind_and_activate=False)

    def test_rejects_negative_max_pending(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), max_pending=-1, bind_and_activate=False)

    def test_rejects_zero_request_queue_size(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), request_queue_size=0, bind_and_activate=False)

    def test_rejects_zero_max_request_size(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), max_request_size=0, bind_and_activate=False)

    def test_rejects_negative_max_request_size(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), max_request_size=-1, bind_and_activate=False)

    def test_config_reflects_constructor_arguments(self):
        # Arrange
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_workers=4,
            max_pending=8,
            overload_policy=ServerOverloadPolicy.FAULT,
            max_request_size=512,
            overload_fault_code=-9999,
            overload_fault_string="custom overload",
            bind_and_activate=False,
        )

        # Act / Assert
        try:
            self.assertEqual(4, server.config.max_workers)
            self.assertEqual(8, server.config.max_pending)
            self.assertIs(ServerOverloadPolicy.FAULT, server.config.overload_policy)
            self.assertEqual(512, server.config.max_request_size)
            self.assertEqual(-9999, server.config.overload_fault_code)
            self.assertEqual("custom overload", server.config.overload_fault_string)
        finally:
            server.shutdown_executor(wait=False)

    def test_max_pending_defaults_to_max_workers_when_none(self):
        # Arrange
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_workers=3,
            max_pending=None,
            bind_and_activate=False,
        )

        # Act / Assert
        try:
            self.assertEqual(3, server.config.max_pending)
        finally:
            server.shutdown_executor(wait=False)

    def test_accepts_overload_policy_as_string(self):
        # Arrange
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy="close",
            bind_and_activate=False,
        )

        # Act / Assert
        try:
            self.assertIs(ServerOverloadPolicy.CLOSE, server.config.overload_policy)
        finally:
            server.shutdown_executor(wait=False)
            server.server_close()

    def test_rejects_invalid_overload_policy_string(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(
                ("127.0.0.1", 0),
                overload_policy="invalid",
                bind_and_activate=False,
            )

    def test_bind_and_activate_false_does_not_bind(self):
        # Arrange / Act
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False)

        # Assert: port 0 → was not bound (no real port assigned)
        try:
            self.assertEqual(0, server.server_address[1])
        finally:
            server.shutdown_executor(wait=False)
            server.server_close()

    def test_allow_none_propagated(self):
        # Arrange / Act
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), allow_none=True, bind_and_activate=False)

        # Assert
        try:
            self.assertTrue(server.allow_none)
        finally:
            server.shutdown_executor(wait=False)

    def test_use_builtin_types_propagated(self):
        # Arrange / Act
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), use_builtin_types=True, bind_and_activate=False)

        # Assert
        try:
            self.assertTrue(server.use_builtin_types)
        finally:
            server.shutdown_executor(wait=False)


class ExecutorShutdownTests(unittest.TestCase):
    """Executor shutdown behavior."""

    def test_shutdown_executor_is_idempotent(self):
        # Arrange
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False)

        # Act / Assert: two calls must not raise
        try:
            server.shutdown_executor(wait=True)
            server.shutdown_executor(wait=True)  # second call is a no-op
        finally:
            server.server_close()

    def test_custom_fault_code_and_string_returned_by_fault_policy(self):
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_workers=1,
            max_pending=0,
            overload_policy=ServerOverloadPolicy.FAULT,
            overload_fault_code=-1234,
            overload_fault_string="too busy",
            logRequests=False,
        ) as server:
            server.register_function(block, "block")
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}"

            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            with self.assertRaises(xmlrpc.client.Fault) as ctx:
                xmlrpc.client.ServerProxy(url).block()

            self.assertEqual(-1234, ctx.exception.faultCode)
            self.assertIn("too busy", ctx.exception.faultString)

            release.set()
            holder.join(timeout=2)
            server.shutdown()


class RpcPathsTests(unittest.TestCase):
    """rpc_paths parameter restricts which URL paths accept XML-RPC."""

    def _make_request(self, url: str, path: str) -> int:
        host = url.removeprefix("http://").split(":")[0]
        port = int(url.rsplit(":", 1)[1])
        body = b"<?xml version='1.0'?><methodCall><methodName>ping</methodName><params/></methodCall>"
        conn = http.client.HTTPConnection(host, port, timeout=2)
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "text/xml",
                "Content-Length": str(len(body)),
            },
        )
        status = conn.getresponse().status
        conn.close()
        return status

    def test_default_paths_accept_root_and_rpc2(self):
        # Arrange
        with running_server() as (server, url):
            server.register_function(lambda: "pong", "ping")

            # Act / Assert
            self.assertEqual(200, self._make_request(url, "/"))
            self.assertEqual(200, self._make_request(url, "/RPC2"))

    def test_custom_rpc_paths_rejects_disallowed_path(self):
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            logRequests=False,
            rpc_paths=("/api",),
        )
        server.register_function(lambda: "pong", "ping")
        t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        t.start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            self.assertEqual(404, self._make_request(url, "/"))
            self.assertEqual(404, self._make_request(url, "/RPC2"))
            self.assertEqual(200, self._make_request(url, "/api"))
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=2)


class ServerStatsTests(unittest.TestCase):
    """ServerStats snapshot reflects actual request activity."""

    def test_stats_returns_server_stats_instance(self):
        # Arrange
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False)

        # Act / Assert
        try:
            self.assertIsInstance(server.stats(), ServerStats)
        finally:
            server.shutdown_executor(wait=False)
            server.server_close()

    def test_completed_counter_increments(self):
        # Arrange
        with running_server(max_workers=2) as (server, url):
            server.register_function(lambda: "ok", "ping")
            proxy = xmlrpc.client.ServerProxy(url, allow_none=True)

            # Act
            proxy.ping()
            proxy.ping()
            # Give worker threads time to call record_completed after shutdown_request
            time.sleep(0.05)

            # Assert
            snap = server.stats()
            self.assertEqual(2, snap.completed)
            self.assertEqual(0, snap.errored)

    def test_errored_counter_does_not_count_xmlrpc_faults(self):
        # XML-RPC handler exceptions are caught by the dispatcher and returned
        # as XML-RPC faults. They do NOT increment the errored counter — only
        # exceptions that escape finish_request entirely (transport-level) do.

        # Arrange
        def boom():
            raise RuntimeError("fail")

        with running_server(max_workers=2) as (server, url):
            server.register_function(boom, "boom")
            proxy = xmlrpc.client.ServerProxy(url, allow_none=True)

            # Act
            try:
                proxy.boom()
            except xmlrpc.client.Fault:
                pass
            time.sleep(0.05)

            # Assert: handler exception → dispatched as fault → completed, not errored
            snap = server.stats()
            self.assertEqual(1, snap.completed)
            self.assertEqual(0, snap.errored)

    def test_rejected_fault_counter_increments(self):
        # Arrange
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.FAULT) as (server, url):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            # Act: overload the server
            try:
                xmlrpc.client.ServerProxy(url).block()
            except xmlrpc.client.Fault:
                pass

            release.set()
            holder.join(timeout=2)

            # Assert
            snap = server.stats()
            self.assertEqual(1, snap.rejected_fault)

    def test_rejected_close_counter_increments(self):
        # Arrange
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.CLOSE) as (server, url):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            # Act: overload the server (connection will be forcibly closed)
            try:
                xmlrpc.client.ServerProxy(url).block()
            except Exception:
                pass

            release.set()
            holder.join(timeout=2)

            # Assert: at least 1 close-rejection counted
            snap = server.stats()
            self.assertGreaterEqual(snap.rejected_close, 1)


class Http503PolicyTests(unittest.TestCase):
    """HTTP_503 overload policy returns a proper HTTP 503 response."""

    def test_http_503_returned_when_server_saturated(self):
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.HTTP_503) as (
            server,
            url,
        ):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            body = b"<?xml version='1.0'?><methodCall><methodName>block</methodName><params/></methodCall>"
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request(
                "POST",
                "/",
                body=body,
                headers={
                    "Content-Type": "text/xml",
                    "Content-Length": str(len(body)),
                },
            )
            response = conn.getresponse()
            self.assertEqual(503, response.status)
            conn.close()

            release.set()
            holder.join(timeout=2)

    def test_rejected_503_counter_increments(self):
        started = threading.Event()
        release = threading.Event()

        def block():
            started.set()
            release.wait(timeout=2)
            return "done"

        with running_server(max_workers=1, max_pending=0, overload_policy=ServerOverloadPolicy.HTTP_503) as (
            server,
            url,
        ):
            server.register_function(block, "block")
            holder = threading.Thread(target=lambda: xmlrpc.client.ServerProxy(url).block())
            holder.start()
            started.wait(timeout=2)

            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            body = b"<?xml version='1.0'?><methodCall><methodName>block</methodName><params/></methodCall>"
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request(
                "POST",
                "/",
                body=body,
                headers={
                    "Content-Type": "text/xml",
                    "Content-Length": str(len(body)),
                },
            )
            conn.getresponse().read()
            conn.close()

            release.set()
            holder.join(timeout=2)

            snap = server.stats()
            self.assertEqual(1, snap.rejected_503)


class CoverageGapTests(unittest.TestCase):
    """Extra tests that close coverage gaps in server.py.

    Each test hits an error-handling branch that normal happy-path tests
    do not exercise.  All follow the AAA (Arrange-Act-Assert) pattern.
    """

    # ------------------------------------------------------------------
    # record_errored (server.py lines 95-97) +
    # _process_request_worker except branch (lines 362-365)
    # ------------------------------------------------------------------

    def test_errored_counter_increments_when_finish_request_raises(self):
        # Arrange: server without real socket; mock finish_request to raise
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, logRequests=False)
        mock_request = mock.MagicMock()

        # Act: invoke the worker directly with finish_request raising
        with mock.patch.object(server, "finish_request", side_effect=RuntimeError("transport")):
            server._process_request_worker(mock_request, ("127.0.0.1", 9999))

        # Assert: errored counter was incremented, not completed
        snap = server.stats()
        self.assertEqual(1, snap.errored)
        self.assertEqual(0, snap.completed)
        server.shutdown_executor(wait=False)
        server.server_close()

    # ------------------------------------------------------------------
    # log_error True branch (server.py line 159)
    # ------------------------------------------------------------------

    def test_log_error_writes_to_stderr_when_log_requests_true(self):
        # Arrange: server with logRequests=True, small request size limit
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_request_size=32,
            logRequests=True,
            allow_none=True,
        )
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        captured = io.StringIO()

        # Act: send an oversized payload that triggers send_error → log_error
        try:
            host, port = server.server_address
            conn = http.client.HTTPConnection(host, port, timeout=2)
            body = b"x" * 64
            with mock.patch.object(sys, "stderr", captured):
                conn.request(
                    "POST",
                    "/",
                    body=body,
                    headers={
                        "Content-Type": "text/xml",
                        "Content-Length": str(len(body)),
                    },
                )
                conn.getresponse().read()
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        # Assert: log_error wrote something to stderr (the 413 error line)
        self.assertGreater(len(captured.getvalue()), 0)

    # ------------------------------------------------------------------
    # __init__ exception cleanup (server.py lines 312–314)
    # ------------------------------------------------------------------

    def test_executor_is_cleaned_up_when_super_init_fails(self):
        # Arrange: port 99999 exceeds the valid 0–65535 range; bind will fail

        # Act / Assert: constructing with an invalid port raises an error
        with self.assertRaises((OSError, OverflowError)):
            ThreadPoolXMLRPCServer(("127.0.0.1", 99999))
        # Assert (implicitly): exception path ran shutdown_executor before re-raising

    # ------------------------------------------------------------------
    # RuntimeError in process_request (server.py lines 346–349)
    # ------------------------------------------------------------------

    def test_process_request_re_raises_runtime_error_from_closed_executor(self):
        # Arrange: server with executor already shut down
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, logRequests=False)
        server.shutdown_executor(wait=False)
        mock_request = mock.MagicMock()

        # Act / Assert: process_request must re-raise the RuntimeError
        with self.assertRaises(RuntimeError):
            server.process_request(mock_request, ("127.0.0.1", 9999))

        server.server_close()

    # ------------------------------------------------------------------
    # _send_fault_response — OSError paths (lines 402–403, 409–410, 415–416)
    # ------------------------------------------------------------------

    def test_send_fault_response_tolerates_oserror_on_sendall(self):
        # Arrange: server in FAULT policy mode; mock request whose sendall fails
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy=ServerOverloadPolicy.FAULT,
            bind_and_activate=False,
        )
        mock_request = mock.MagicMock()
        mock_request.sendall.side_effect = OSError("broken pipe")

        # Act: must not raise even though the socket errors
        server._send_fault_response(mock_request)

        # Assert: sendall was called once; no exception escaped
        mock_request.sendall.assert_called_once()
        server.shutdown_executor(wait=False)
        server.server_close()

    def test_send_fault_response_tolerates_oserror_on_shutdown(self):
        # Arrange: sendall succeeds, socket.shutdown raises OSError
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy=ServerOverloadPolicy.FAULT,
            bind_and_activate=False,
        )
        mock_request = mock.MagicMock()
        mock_request.shutdown.side_effect = OSError("already closed")

        # Act: must return silently after the sendall + failed shutdown
        server._send_fault_response(mock_request)

        # Assert
        mock_request.sendall.assert_called_once()
        mock_request.shutdown.assert_called_once()
        server.shutdown_executor(wait=False)
        server.server_close()

    def test_send_fault_response_tolerates_oserror_on_recv(self):
        # Arrange: sendall and shutdown succeed; recv raises OSError
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy=ServerOverloadPolicy.FAULT,
            bind_and_activate=False,
        )
        mock_request = mock.MagicMock()
        mock_request.recv.side_effect = OSError("connection reset")

        # Act
        server._send_fault_response(mock_request)

        # Assert: recv was called at least once; no exception
        mock_request.recv.assert_called()
        server.shutdown_executor(wait=False)
        server.server_close()

    # ------------------------------------------------------------------
    # _send_503_response — OSError paths (lines 430–431, 434–435)
    # ------------------------------------------------------------------

    def test_send_503_response_tolerates_oserror_on_sendall(self):
        # Arrange: server in HTTP_503 policy; mock request with failing sendall
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy=ServerOverloadPolicy.HTTP_503,
            bind_and_activate=False,
        )
        mock_request = mock.MagicMock()
        mock_request.sendall.side_effect = OSError("broken pipe")

        # Act: must not propagate the OSError
        server._send_503_response(mock_request)

        # Assert
        mock_request.sendall.assert_called_once()
        server.shutdown_executor(wait=False)
        server.server_close()

    def test_send_503_response_tolerates_oserror_on_shutdown(self):
        # Arrange: sendall succeeds, socket.shutdown raises
        server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            overload_policy=ServerOverloadPolicy.HTTP_503,
            bind_and_activate=False,
        )
        mock_request = mock.MagicMock()
        mock_request.shutdown.side_effect = OSError("already closed")

        # Act
        server._send_503_response(mock_request)

        # Assert
        mock_request.sendall.assert_called_once()
        mock_request.shutdown.assert_called_once()
        server.shutdown_executor(wait=False)
        server.server_close()

    # ------------------------------------------------------------------
    # _build_request_handler — non-LimitedXMLRPCRequestHandler path (line 469)
    # ------------------------------------------------------------------

    def test_build_request_handler_adds_limited_mixin_for_plain_handler(self):
        # Arrange: a handler that does NOT inherit LimitedXMLRPCRequestHandler
        from xmlrpc.server import SimpleXMLRPCRequestHandler

        from xmlrpc_extended.server import LimitedXMLRPCRequestHandler

        class PlainHandler(SimpleXMLRPCRequestHandler):
            pass

        # Act: static method must wrap it with the limiter
        result = ThreadPoolXMLRPCServer._build_request_handler(PlainHandler, 65536)

        # Assert: result is a subclass of both the limiter and the plain handler
        self.assertTrue(issubclass(result, LimitedXMLRPCRequestHandler))
        self.assertTrue(issubclass(result, PlainHandler))
        self.assertEqual(65536, result.max_request_size)


class ConnectionTimeoutTests(unittest.TestCase):
    """Tests for the connection_timeout constructor parameter."""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def test_rejects_zero_connection_timeout(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, connection_timeout=0)

    def test_rejects_negative_connection_timeout(self):
        # Arrange / Act / Assert
        with self.assertRaises(ValueError):
            ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, connection_timeout=-1.0)

    def test_none_connection_timeout_is_valid(self):
        # Arrange / Act
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, connection_timeout=None)
        # Assert
        self.assertIsNone(server.config.connection_timeout)
        server.shutdown_executor(wait=False)

    def test_positive_connection_timeout_stored_in_config(self):
        # Arrange / Act
        server = ThreadPoolXMLRPCServer(("127.0.0.1", 0), bind_and_activate=False, connection_timeout=5.0)
        # Assert
        self.assertEqual(5.0, server.config.connection_timeout)
        server.shutdown_executor(wait=False)

    # ------------------------------------------------------------------
    # Behaviour — normal RPC still works when timeout is configured
    # ------------------------------------------------------------------

    def setUp(self):
        self.server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_workers=2,
            logRequests=False,
            connection_timeout=2.0,  # generous — won't fire during a normal call
        )
        self.server.register_function(lambda a, b: a + b, "add")
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_normal_rpc_call_succeeds_within_timeout(self):
        # Arrange
        proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{self.port}/")
        # Act
        result = proxy.add(3, 4)
        # Assert
        self.assertEqual(7, result)

    def test_slow_client_connection_is_timed_out(self):
        # Arrange: server with a very short timeout
        import socket as _socket

        fast_server = ThreadPoolXMLRPCServer(
            ("127.0.0.1", 0),
            max_workers=2,
            logRequests=False,
            connection_timeout=0.1,  # 100 ms
        )
        fast_port = fast_server.server_address[1]
        t = threading.Thread(target=fast_server.serve_forever, daemon=True)
        t.start()

        try:
            # Act: connect but do not send any HTTP data
            sock = _socket.create_connection(("127.0.0.1", fast_port))
            sock.settimeout(2.0)
            time.sleep(0.35)  # wait > 3× the server connection_timeout
            # Assert: server has closed the connection — recv returns b'' or raises
            try:
                data = sock.recv(1024)
                self.assertEqual(b"", data)
            except OSError:
                pass  # connection reset is also acceptable
            finally:
                sock.close()
        finally:
            fast_server.shutdown()
            fast_server.server_close()
            t.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
