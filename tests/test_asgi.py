"""Tests for xmlrpc_extended.asgi.XMLRPCASGIApp.

All tests follow the Arrange-Act-Assert (AAA) pattern:

  # Arrange – set up inputs and preconditions
  # Act     – call the code under test
  # Assert  – verify the outcome

Test structure
--------------
- XMLRPCASGIAppSmokeTests     – module import and construction
- XMLRPCASGIAppCallTests      – basic XML-RPC call semantics (sync + async)
- XMLRPCASGIAppHttpTests      – HTTP-level behaviour (404, 405, 413, content-type)
- XMLRPCASGIAppLifespanTests  – ASGI lifespan startup/shutdown
- XMLRPCASGIAppDispatchTests  – dispatch edge cases (instance, dotted, unknown)
- XMLRPCASGIAppIntrospectionTests – system.* introspection methods
- XMLRPCASGIAppErrorTests     – fault and exception handling
- XMLRPCASGIAppConcurrencyTests – concurrent requests and thread pool
"""

from __future__ import annotations

import asyncio
import threading
import unittest
import xmlrpc.client

import httpx

from xmlrpc_extended.asgi import XMLRPCASGIApp

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _xml_request(method: str, *args: object) -> bytes:
    """Return a well-formed XML-RPC request body."""
    return xmlrpc.client.dumps(args, method).encode()


def _parse_response(body: bytes) -> object:
    """Unwrap an XML-RPC response body; raise on fault."""
    result, _ = xmlrpc.client.loads(body)
    return result[0]


def _run(coro: object) -> object:
    """Run a coroutine synchronously."""
    return asyncio.run(coro)  # type: ignore[arg-type]


def _make_client(app: XMLRPCASGIApp, base_url: str = "http://test") -> httpx.AsyncClient:
    """Return an httpx.AsyncClient backed by an in-process ASGI transport."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url=base_url)


async def _post_rpc(
    app: XMLRPCASGIApp,
    method: str,
    *args: object,
    path: str = "/",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Post a single XML-RPC request to the app and return the raw response."""
    body = _xml_request(method, *args)
    req_headers = {"Content-Type": "text/xml"}
    if headers:
        req_headers.update(headers)
    async with _make_client(app) as client:
        return await client.post(path, content=body, headers=req_headers)


# ---------------------------------------------------------------------------
# XMLRPCASGIAppSmokeTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppSmokeTests(unittest.TestCase):
    """Verify that the module can be imported and a basic app created."""

    def test_module_is_importable(self) -> None:
        # Arrange – nothing to set up
        # Act
        import xmlrpc_extended.asgi as asgi_module

        # Assert
        self.assertTrue(hasattr(asgi_module, "XMLRPCASGIApp"))

    def test_default_construction_succeeds(self) -> None:
        # Arrange – use all defaults
        # Act
        app = XMLRPCASGIApp()

        # Assert: app is callable and has expected defaults
        self.assertIsInstance(app, XMLRPCASGIApp)
        self.assertIsNone(app._executor)

    def test_custom_params_are_stored(self) -> None:
        # Arrange
        workers, size, path = 8, 2_097_152, "/rpc"

        # Act
        app = XMLRPCASGIApp(max_workers=workers, max_request_size=size, rpc_path=path)

        # Assert
        self.assertEqual(app._max_workers, workers)
        self.assertEqual(app._max_request_size, size)
        self.assertEqual(app._rpc_path, path)

    def test_zero_max_workers_raises_value_error(self) -> None:
        # Arrange – invalid argument
        # Act / Assert
        with self.assertRaises(ValueError, msg="max_workers=0 should raise"):
            XMLRPCASGIApp(max_workers=0)

    def test_negative_max_workers_raises_value_error(self) -> None:
        # Arrange
        # Act / Assert
        with self.assertRaises(ValueError):
            XMLRPCASGIApp(max_workers=-1)

    def test_zero_max_request_size_raises_value_error(self) -> None:
        # Arrange
        # Act / Assert
        with self.assertRaises(ValueError):
            XMLRPCASGIApp(max_request_size=0)

    def test_close_with_no_executor_is_a_noop(self) -> None:
        # Arrange: app that was never called (no executor yet)
        app = XMLRPCASGIApp()

        # Act / Assert – must not raise
        app.close()
        self.assertIsNone(app._executor)


# ---------------------------------------------------------------------------
# XMLRPCASGIAppCallTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppCallTests(unittest.TestCase):
    """Verify that sync and async RPC handlers produce correct results."""

    def setUp(self) -> None:
        # Arrange (shared): a fresh app with one sync and one async handler
        self.app = XMLRPCASGIApp(max_workers=2)
        self.app.register_function(lambda a, b: a + b, "add")

        async def async_multiply(a: int, b: int) -> int:
            await asyncio.sleep(0)  # yield to event loop
            return a * b

        self.app.register_function(async_multiply, "multiply")

    def tearDown(self) -> None:
        self.app.close()

    def test_sync_function_returns_correct_result(self) -> None:
        # Arrange
        async def _call() -> int:
            response = await _post_rpc(self.app, "add", 3, 4)
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())

        # Assert
        self.assertEqual(result, 7)

    def test_async_function_is_awaited_and_returns_correct_result(self) -> None:
        # Arrange
        async def _call() -> int:
            response = await _post_rpc(self.app, "multiply", 6, 7)
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())

        # Assert
        self.assertEqual(result, 42)

    def test_response_status_code_is_200_for_valid_calls(self) -> None:
        # Arrange
        async def _call() -> int:
            response = await _post_rpc(self.app, "add", 1, 2)
            return response.status_code

        # Act
        status = _run(_call())

        # Assert
        self.assertEqual(status, 200)

    def test_response_content_type_is_text_xml(self) -> None:
        # Arrange
        async def _call() -> str:
            response = await _post_rpc(self.app, "add", 1, 2)
            return response.headers["content-type"]

        # Act
        content_type = _run(_call())

        # Assert
        self.assertIn("text/xml", content_type)

    def test_allow_none_false_raises_fault_for_none_return(self) -> None:
        # Arrange: app with allow_none=False, handler returning None
        app = XMLRPCASGIApp(allow_none=False)
        app.register_function(lambda: None, "null")

        async def _call() -> dict[str, object]:
            response = await _post_rpc(app, "null")
            # Response should be XML-RPC fault (encoded in 200)
            try:
                xmlrpc.client.loads(response.content)
                return {"fault": False}
            except xmlrpc.client.Fault as f:
                return {"fault": True, "code": f.faultCode}

        # Act
        result = _run(_call())

        # Assert
        app.close()
        # allow_none=False + None return → marshaling error → fault code 1
        self.assertTrue(result["fault"])

    def test_allow_none_true_accepts_none_return(self) -> None:
        # Arrange
        app = XMLRPCASGIApp(allow_none=True)
        app.register_function(lambda: None, "null")

        async def _call() -> object:
            response = await _post_rpc(app, "null")
            return _parse_response(response.content)

        # Act
        result = _run(_call())
        app.close()

        # Assert
        self.assertIsNone(result)

    def test_multiple_sequential_calls_return_independent_results(self) -> None:
        # Arrange
        async def _call() -> list[int]:
            results = []
            async with _make_client(self.app) as client:
                for a, b in [(1, 2), (10, 20), (100, 200)]:
                    body = _xml_request("add", a, b)
                    resp = await client.post("/", content=body, headers={"Content-Type": "text/xml"})
                    results.append(_parse_response(resp.content))  # type: ignore[arg-type]
            return results

        # Act
        results = _run(_call())

        # Assert
        self.assertEqual(results, [3, 30, 300])


# ---------------------------------------------------------------------------
# XMLRPCASGIAppHttpTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppHttpTests(unittest.TestCase):
    """Verify HTTP-level protocol enforcement."""

    def setUp(self) -> None:
        # Arrange (shared): minimal app at default path "/"
        self.app = XMLRPCASGIApp()
        self.app.register_function(lambda: "pong", "ping")

    def tearDown(self) -> None:
        self.app.close()

    def test_wrong_path_returns_404(self) -> None:
        # Arrange
        async def _call() -> int:
            response = await _post_rpc(self.app, "ping", path="/wrong")
            return response.status_code

        # Act
        status = _run(_call())

        # Assert
        self.assertEqual(status, 404)

    def test_get_request_returns_405(self) -> None:
        # Arrange
        async def _call() -> int:
            async with _make_client(self.app) as client:
                response = await client.get("/")
            return response.status_code

        # Act
        status = _run(_call())

        # Assert
        self.assertEqual(status, 405)

    def test_get_request_includes_allow_header(self) -> None:
        # Arrange
        async def _call() -> str:
            async with _make_client(self.app) as client:
                response = await client.get("/")
            return response.headers.get("allow", "")

        # Act
        allow = _run(_call())

        # Assert
        self.assertIn("POST", allow.upper())

    def test_oversized_body_returns_413(self) -> None:
        # Arrange: app with tiny limit; build a body that exceeds it
        app = XMLRPCASGIApp(max_request_size=100)
        app.register_function(lambda: "ok", "ping")
        oversized_body = b"x" * 200

        async def _call() -> int:
            async with _make_client(app) as client:
                response = await client.post("/", content=oversized_body)
            return response.status_code

        # Act
        status = _run(_call())
        app.close()

        # Assert
        self.assertEqual(status, 413)

    def test_body_exactly_at_limit_is_accepted(self) -> None:
        # Arrange: XML payload that is exactly at the configured limit
        body = _xml_request("ping")
        app = XMLRPCASGIApp(max_request_size=len(body))
        app.register_function(lambda: "pong", "ping")

        async def _call() -> int:
            async with _make_client(app) as client:
                response = await client.post("/", content=body, headers={"Content-Type": "text/xml"})
            return response.status_code

        # Act
        status = _run(_call())
        app.close()

        # Assert
        self.assertEqual(status, 200)

    def test_custom_rpc_path_rejects_root(self) -> None:
        # Arrange: app listening on /rpc only
        app = XMLRPCASGIApp(rpc_path="/rpc")
        app.register_function(lambda: "pong", "ping")

        async def _call() -> int:
            response = await _post_rpc(app, "ping", path="/")  # should 404
            return response.status_code

        # Act
        status = _run(_call())
        app.close()

        # Assert
        self.assertEqual(status, 404)

    def test_custom_rpc_path_accepts_correct_path(self) -> None:
        # Arrange
        app = XMLRPCASGIApp(rpc_path="/rpc")
        app.register_function(lambda: "pong", "ping")

        async def _call() -> int:
            response = await _post_rpc(app, "ping", path="/rpc")
            return response.status_code

        # Act
        status = _run(_call())
        app.close()

        # Assert
        self.assertEqual(status, 200)


# ---------------------------------------------------------------------------
# XMLRPCASGIAppLifespanTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppLifespanTests(unittest.TestCase):
    """Verify ASGI lifespan startup and shutdown handling."""

    def test_lifespan_startup_creates_executor(self) -> None:
        # Arrange
        app = XMLRPCASGIApp()
        events_out: list[dict] = []

        async def fake_receive() -> dict:
            return {"type": "lifespan.startup"}

        async def fake_send(msg: dict) -> None:
            events_out.append(msg)

        async def _run_lifespan() -> None:
            # Drive one startup event then stop by simulating shutdown
            startup_done = asyncio.Event()

            async def receive_gen() -> dict:
                if not startup_done.is_set():
                    startup_done.set()
                    return {"type": "lifespan.startup"}
                return {"type": "lifespan.shutdown"}

            await app._handle_lifespan({}, receive_gen, fake_send)  # type: ignore[arg-type]

        # Act
        _run(_run_lifespan())

        # Assert: both startup.complete and shutdown.complete were sent
        types = [e["type"] for e in events_out]
        self.assertIn("lifespan.startup.complete", types)
        self.assertIn("lifespan.shutdown.complete", types)
        self.assertIsNone(app._executor)  # shutdown cleaned up

    def test_lifespan_shutdown_closes_executor(self) -> None:
        # Arrange: app whose executor is pre-created (simulates active server)
        app = XMLRPCASGIApp()
        app.register_function(lambda: "pong", "ping")
        # Trigger lazy executor creation
        _run(_post_rpc(app, "ping"))

        executor_was_running = app._executor is not None

        shutdown_msgs: list[dict] = []

        async def receive_shutdown() -> dict:
            return {"type": "lifespan.shutdown"}

        async def collect_send(msg: dict) -> None:
            shutdown_msgs.append(msg)

        # Act
        _run(app._handle_lifespan({}, receive_shutdown, collect_send))  # type: ignore[arg-type]

        # Assert
        self.assertTrue(executor_was_running)
        self.assertIsNone(app._executor)
        self.assertEqual(shutdown_msgs[-1]["type"], "lifespan.shutdown.complete")

    def test_close_shuts_down_executor(self) -> None:
        # Arrange: trigger executor creation via a call
        app = XMLRPCASGIApp()
        app.register_function(lambda: "x", "x")
        _run(_post_rpc(app, "x"))
        self.assertIsNotNone(app._executor)

        # Act
        app.close()

        # Assert
        self.assertIsNone(app._executor)

    def test_lifespan_ignores_unknown_event_types_and_continues(self) -> None:
        # Arrange: send an unknown lifespan event, then shutdown
        # This covers the branch where neither "startup" nor "shutdown" is received
        app = XMLRPCASGIApp()
        sent: list[dict] = []
        call_count = 0

        async def receive_seq() -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "lifespan.unknown_event"}  # ignored, loops back
            return {"type": "lifespan.shutdown"}  # terminates

        async def collect_send(msg: dict) -> None:
            sent.append(msg)

        # Act
        _run(app._handle_lifespan({}, receive_seq, collect_send))  # type: ignore[arg-type]

        # Assert: only the shutdown.complete was sent (no startup event triggered startup)
        self.assertEqual(sent[-1]["type"], "lifespan.shutdown.complete")
        self.assertEqual(call_count, 2)

    def test_lifespan_shutdown_when_executor_is_none_is_safe(self) -> None:
        # Arrange: app whose executor was never created (no startup event)
        app = XMLRPCASGIApp()
        self.assertIsNone(app._executor)
        sent: list[dict] = []

        async def receive_shutdown() -> dict:
            return {"type": "lifespan.shutdown"}

        async def collect_send(msg: dict) -> None:
            sent.append(msg)

        # Act: shutdown without prior startup should not raise
        _run(app._handle_lifespan({}, receive_shutdown, collect_send))  # type: ignore[arg-type]

        # Assert: shutdown.complete was sent and executor is still None
        self.assertEqual(sent[-1]["type"], "lifespan.shutdown.complete")
        self.assertIsNone(app._executor)

    def test_close_is_idempotent(self) -> None:
        # Arrange
        app = XMLRPCASGIApp()
        app.register_function(lambda: "x", "x")
        _run(_post_rpc(app, "x"))

        # Act: call close twice
        app.close()
        app.close()  # must not raise

        # Assert
        self.assertIsNone(app._executor)

    def test_call_dispatches_lifespan_scope_through_main_entry_point(self) -> None:
        # Arrange: verify the __call__ lifespan routing branch (asgi.py line 176)
        app = XMLRPCASGIApp()
        sent: list[dict] = []

        async def _run_lifespan() -> None:
            call_count = 0

            async def receive_gen() -> dict:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return {"type": "lifespan.startup"}
                return {"type": "lifespan.shutdown"}

            async def send(msg: dict) -> None:
                sent.append(msg)

            # Call through __call__, NOT _handle_lifespan directly
            await app({"type": "lifespan"}, receive_gen, send)

        # Act
        _run(_run_lifespan())

        # Assert: both lifecycle events were acknowledged via __call__
        types = [e["type"] for e in sent]
        self.assertIn("lifespan.startup.complete", types)
        self.assertIn("lifespan.shutdown.complete", types)

    def test_call_ignores_unknown_scope_types(self) -> None:
        # Arrange: send an unsupported scope type (e.g. "websocket")
        app = XMLRPCASGIApp()

        async def noop_receive() -> dict:
            return {}

        async def noop_send(msg: dict) -> None:
            pass

        # Act / Assert: must not raise
        _run(app({"type": "websocket"}, noop_receive, noop_send))


# ---------------------------------------------------------------------------
# XMLRPCASGIAppDispatchTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppDispatchTests(unittest.TestCase):
    """Verify dispatch edge cases: instance, dotted names, unknown methods."""

    def tearDown(self) -> None:
        pass  # each test creates and closes its own app

    def test_register_instance_sync_method_is_callable(self) -> None:
        # Arrange
        class MyService:
            def echo(self, value: str) -> str:
                return value

        app = XMLRPCASGIApp()
        app.register_instance(MyService())

        async def _call() -> str:
            response = await _post_rpc(app, "echo", "hello")
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())
        app.close()

        # Assert
        self.assertEqual(result, "hello")

    def test_register_instance_async_method_is_awaited(self) -> None:
        # Arrange
        class AsyncService:
            async def greet(self, name: str) -> str:
                await asyncio.sleep(0)
                return f"Hello {name}"

        app = XMLRPCASGIApp()
        app.register_instance(AsyncService())

        async def _call() -> str:
            response = await _post_rpc(app, "greet", "World")
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())
        app.close()

        # Assert
        self.assertEqual(result, "Hello World")

    def test_instance_with_custom_dispatch_is_called(self) -> None:
        # Arrange: instance with _dispatch for custom resolution
        class DispatchingService:
            def _dispatch(self, method: str, params: tuple) -> object:
                match method:
                    case "calc.add":
                        return params[0] + params[1]
                    case _:
                        raise Exception(f"method {method!r} not supported")

        app = XMLRPCASGIApp()
        app.register_instance(DispatchingService())

        async def _call() -> int:
            response = await _post_rpc(app, "calc.add", 10, 5)
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())
        app.close()

        # Assert
        self.assertEqual(result, 15)

    def test_instance_with_async_custom_dispatch_is_awaited(self) -> None:
        # Arrange
        class AsyncDispatcher:
            async def _dispatch(self, method: str, params: tuple) -> object:
                await asyncio.sleep(0)
                return f"dispatched:{method}"

        app = XMLRPCASGIApp()
        app.register_instance(AsyncDispatcher())

        async def _call() -> str:
            response = await _post_rpc(app, "any.method")
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())
        app.close()

        # Assert
        self.assertEqual(result, "dispatched:any.method")

    def test_unknown_method_returns_xmlrpc_fault(self) -> None:
        # Arrange: app with no registered methods
        app = XMLRPCASGIApp()

        async def _call() -> xmlrpc.client.Fault | None:
            response = await _post_rpc(app, "does_not_exist")
            try:
                xmlrpc.client.loads(response.content)
                return None
            except xmlrpc.client.Fault as f:
                return f

        # Act
        fault = _run(_call())
        app.close()

        # Assert
        self.assertIsNotNone(fault)
        self.assertIsInstance(fault, xmlrpc.client.Fault)
        self.assertIn("not supported", str(fault.faultString).lower())

    def test_registered_function_takes_precedence_over_instance(self) -> None:
        # Arrange: both a registered function and an instance define "add"
        class FallbackService:
            def add(self, a: int, b: int) -> int:
                return a + b + 1000  # different result

        app = XMLRPCASGIApp()
        app.register_function(lambda a, b: a + b, "add")  # should win
        app.register_instance(FallbackService())

        async def _call() -> int:
            response = await _post_rpc(app, "add", 1, 2)
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        result = _run(_call())
        app.close()

        # Assert: registered function (sum=3) takes precedence, not 1003
        self.assertEqual(result, 3)

    def test_instance_attribute_error_returns_fault_for_unknown_method(self) -> None:
        # Arrange: instance without _dispatch and without the method
        class PartialService:
            def known(self) -> str:
                return "ok"

        app = XMLRPCASGIApp()
        app.register_instance(PartialService())

        async def _call() -> xmlrpc.client.Fault | None:
            response = await _post_rpc(app, "unknown_method")
            try:
                xmlrpc.client.loads(response.content)
                return None
            except xmlrpc.client.Fault as f:
                return f

        # Act
        fault = _run(_call())
        app.close()

        # Assert
        self.assertIsNotNone(fault)


# ---------------------------------------------------------------------------
# XMLRPCASGIAppIntrospectionTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppIntrospectionTests(unittest.TestCase):
    """Verify XML-RPC introspection (system.* methods)."""

    def setUp(self) -> None:
        # Arrange (shared): app with introspection and a couple of functions
        self.app = XMLRPCASGIApp()
        self.app.register_function(lambda a, b: a + b, "add")
        self.app.register_function(lambda x: x * 2, "double")
        self.app.register_introspection_functions()
        self.app.register_multicall_functions()

    def tearDown(self) -> None:
        self.app.close()

    def test_system_list_methods_includes_registered_functions(self) -> None:
        # Arrange
        async def _call() -> list[str]:
            response = await _post_rpc(self.app, "system.listMethods")
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        methods = _run(_call())

        # Assert
        self.assertIn("add", methods)
        self.assertIn("double", methods)
        self.assertIn("system.listMethods", methods)

    def test_system_multicall_executes_multiple_calls(self) -> None:
        # Arrange: two calls bundled into system.multicall
        calls = [
            {"methodName": "add", "params": [1, 2]},
            {"methodName": "double", "params": [5]},
        ]

        async def _call() -> list[object]:
            response = await _post_rpc(self.app, "system.multicall", calls)
            return _parse_response(response.content)  # type: ignore[return-value]

        # Act
        results = _run(_call())

        # Assert
        self.assertEqual(results[0][0], 3)  # add(1, 2) = 3
        self.assertEqual(results[1][0], 10)  # double(5) = 10


# ---------------------------------------------------------------------------
# XMLRPCASGIAppErrorTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppErrorTests(unittest.TestCase):
    """Verify fault responses for invalid payloads and handler exceptions."""

    def setUp(self) -> None:
        # Arrange (shared): app with handlers that can raise
        self.app = XMLRPCASGIApp()

        def always_raises() -> None:
            raise RuntimeError("handler failure")

        async def async_raises() -> None:
            raise ValueError("async failure")

        self.app.register_function(always_raises, "raise")
        self.app.register_function(async_raises, "async_raise")

    def tearDown(self) -> None:
        self.app.close()

    def test_handler_exception_becomes_xmlrpc_fault_code_1(self) -> None:
        # Arrange
        async def _call() -> xmlrpc.client.Fault | None:
            response = await _post_rpc(self.app, "raise")
            try:
                xmlrpc.client.loads(response.content)
                return None
            except xmlrpc.client.Fault as f:
                return f

        # Act
        fault = _run(_call())

        # Assert: handler exception → fault code 1, message contains exception info
        self.assertIsNotNone(fault)
        assert fault is not None
        self.assertEqual(fault.faultCode, 1)
        self.assertIn("RuntimeError", fault.faultString)

    def test_async_handler_exception_becomes_xmlrpc_fault(self) -> None:
        # Arrange
        async def _call() -> xmlrpc.client.Fault | None:
            response = await _post_rpc(self.app, "async_raise")
            try:
                xmlrpc.client.loads(response.content)
                return None
            except xmlrpc.client.Fault as f:
                return f

        # Act
        fault = _run(_call())

        # Assert
        self.assertIsNotNone(fault)
        assert fault is not None
        self.assertIn("ValueError", fault.faultString)

    def test_malformed_xml_body_returns_fault_code_minus_32700(self) -> None:
        # Arrange: send non-XML bytes
        async def _call() -> int:
            async with _make_client(self.app) as client:
                response = await client.post(
                    "/",
                    content=b"NOT XML AT ALL",
                    headers={"Content-Type": "text/xml"},
                )
            # The response is 200 but with a fault body
            try:
                result, _ = xmlrpc.client.loads(response.content)
                return 0  # no fault → unexpected
            except xmlrpc.client.Fault as f:
                return f.faultCode

        # Act
        fault_code = _run(_call())

        # Assert: XML parse error → fault code -32700
        self.assertEqual(fault_code, -32700)

    def test_response_is_200_even_for_fault_responses(self) -> None:
        # Arrange: XML-RPC spec mandates 200 OK even for faults
        async def _call() -> int:
            response = await _post_rpc(self.app, "not_registered")
            return response.status_code

        # Act
        status = _run(_call())

        # Assert: HTTP 200 even when XML-RPC fault in body
        self.assertEqual(status, 200)


# ---------------------------------------------------------------------------
# XMLRPCASGIAppConcurrencyTests
# ---------------------------------------------------------------------------


class XMLRPCASGIAppConcurrencyTests(unittest.TestCase):
    """Verify concurrent requests are handled correctly."""

    def test_concurrent_async_handlers_run_in_parallel(self) -> None:
        # Arrange: async handler that sleeps briefly; fire N concurrently
        call_order: list[str] = []
        lock = threading.Lock()

        async def slow(label: str) -> str:
            await asyncio.sleep(0.05)
            with lock:
                call_order.append(label)
            return label

        app = XMLRPCASGIApp(max_workers=1)
        app.register_function(slow, "slow")

        async def _run_concurrent() -> list[str]:
            async with _make_client(app) as client:
                tasks = [
                    client.post("/", content=_xml_request("slow", lbl), headers={"Content-Type": "text/xml"})
                    for lbl in ["a", "b", "c", "d"]
                ]
                responses = await asyncio.gather(*tasks)
            return [_parse_response(r.content) for r in responses]  # type: ignore[misc]

        # Act
        import time

        t0 = time.perf_counter()
        results = _run(_run_concurrent())
        elapsed = time.perf_counter() - t0

        app.close()

        # Assert: all 4 calls completed and ran concurrently (< 4 × 0.05 s)
        self.assertEqual(sorted(results), ["a", "b", "c", "d"])
        self.assertLess(elapsed, 0.18, "Async handlers should run concurrently")

    def test_concurrent_sync_handlers_run_in_thread_pool(self) -> None:
        # Arrange: sync handler with a small sleep; fire N concurrently
        import time

        def slow_sync(label: str) -> str:
            time.sleep(0.05)
            return label

        app = XMLRPCASGIApp(max_workers=4)
        app.register_function(slow_sync, "slow_sync")

        async def _run_concurrent() -> list[str]:
            async with _make_client(app) as client:
                tasks = [
                    client.post("/", content=_xml_request("slow_sync", lbl), headers={"Content-Type": "text/xml"})
                    for lbl in ["a", "b", "c", "d"]
                ]
                responses = await asyncio.gather(*tasks)
            return [_parse_response(r.content) for r in responses]  # type: ignore[misc]

        # Act
        t0 = time.perf_counter()
        results = _run(_run_concurrent())
        elapsed = time.perf_counter() - t0

        app.close()

        # Assert: thread-pool allows overlap; should be ~0.05 s not ~0.2 s
        self.assertEqual(sorted(results), ["a", "b", "c", "d"])
        self.assertLess(elapsed, 0.18, "Sync handlers should run in thread pool concurrently")

    def test_lazy_executor_created_without_lifespan(self) -> None:
        # Arrange: app that never went through lifespan startup
        app = XMLRPCASGIApp(max_workers=2)
        app.register_function(lambda: "ok", "ping")
        self.assertIsNone(app._executor)

        # Act
        _run(_post_rpc(app, "ping"))

        # Assert: executor was created lazily
        self.assertIsNotNone(app._executor)
        app.close()


if __name__ == "__main__":
    unittest.main()
