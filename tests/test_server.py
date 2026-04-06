import http.client
import io
import sys
import threading
import time
import unittest
import xmlrpc.client
from contextlib import contextmanager
from unittest import mock

from xmlrpc_extended import ServerOverloadPolicy, ThreadPoolXMLRPCServer


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
        def add(left, right):
            return left + right

        class Methods:
            def ping(self):
                return "pong"

        with running_server() as (server, url):
            server.register_function(add, "add")
            server.register_instance(Methods())
            proxy = xmlrpc.client.ServerProxy(url, allow_none=True)
            self.assertIn("system.listMethods", proxy.system.listMethods())
            self.assertIn("add", proxy.system.listMethods())
            self.assertIn("ping", proxy.system.listMethods())
            self.assertEqual(5, proxy.add(2, 3))
            self.assertEqual("pong", proxy.ping())

    def test_processes_requests_concurrently(self):
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

            threads = [threading.Thread(target=invoke) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

            self.assertEqual(2, len(results))
            self.assertEqual(["ok", "ok"], sorted(results))
            self.assertEqual(2, max_active)

    def test_close_policy_rejects_requests_when_server_is_saturated(self):
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

            with self.assertRaises((OSError, xmlrpc.client.ProtocolError, http.client.HTTPException)):
                xmlrpc.client.ServerProxy(url).block()

            release.set()
            holder.join(timeout=2)

    def test_fault_policy_returns_xmlrpc_fault_when_server_is_saturated(self):
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

            with self.assertRaises(xmlrpc.client.Fault) as error:
                xmlrpc.client.ServerProxy(url).block()

            self.assertEqual(-32500, error.exception.faultCode)
            self.assertIn("overloaded", error.exception.faultString.lower())

            release.set()
            holder.join(timeout=2)

    def test_server_close_waits_for_inflight_requests(self):
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

            def stop_server():
                server.shutdown()
                server.server_close()

            stopper = threading.Thread(target=stop_server)
            stopper.start()
            time.sleep(0.1)
            self.assertTrue(stopper.is_alive())

            release.set()

            stopper.join(timeout=2)
            client_thread.join(timeout=2)

    def test_rejects_oversized_xmlrpc_payloads(self):
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)
            body = b"x" * 33

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

            self.assertEqual(413, response.status)
            connection.close()

    def test_rejects_invalid_content_length_header(self):
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Content-Length", "abc")
            connection.endheaders()
            response = connection.getresponse()

            self.assertEqual(400, response.status)
            connection.close()

    def test_rejects_missing_content_length_header(self):
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.endheaders()
            response = connection.getresponse()

            self.assertEqual(411, response.status)
            connection.close()

    def test_rejects_negative_content_length(self):
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Content-Length", "-1")
            connection.endheaders()
            response = connection.getresponse()

            self.assertEqual(400, response.status)
            connection.close()

    def test_rejects_chunked_transfer_encoding(self):
        with running_server(max_request_size=1024) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            connection.putrequest("POST", "/")
            connection.putheader("Content-Type", "text/xml")
            connection.putheader("Transfer-Encoding", "chunked")
            connection.endheaders()
            response = connection.getresponse()

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
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)
            body = b"x" * 33

            captured = io.StringIO()
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

            self.assertEqual(413, response.status)
            self.assertEqual("", captured.getvalue())
            connection.close()

    def test_invalid_content_length_does_not_log_when_log_requests_false(self):
        with running_server(max_request_size=32) as (_, url):
            host = url.removeprefix("http://").split(":")[0]
            port = int(url.rsplit(":", 1)[1])
            connection = http.client.HTTPConnection(host, port, timeout=2)

            captured = io.StringIO()
            with mock.patch.object(sys, "stderr", captured):
                connection.putrequest("POST", "/")
                connection.putheader("Content-Type", "text/xml")
                connection.putheader("Content-Length", "abc")
                connection.endheaders()
                response = connection.getresponse()

            self.assertEqual(400, response.status)
            self.assertEqual("", captured.getvalue())
            connection.close()


if __name__ == "__main__":
    unittest.main()
