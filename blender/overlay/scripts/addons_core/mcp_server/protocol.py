# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Model Context Protocol (MCP) server, Streamable HTTP transport.

Implements both protocol eras (see https://modelcontextprotocol.io/specification):

- Modern (2026-07-28): stateless, every request carries its protocol version in ``_meta``
  (mirrored in HTTP headers), ``server/discover``.
- Legacy (2025-03-26 to 2025-11-25): ``initialize`` handshake.

Tools are called through an executor, which runs them on Blender's main thread.
This module doesn't depend on ``bpy``.
"""

__all__ = (
    "Server",
    "Tool",
    "ToolError",
)

import base64
import collections
import hmac
import http.server
import json
import secrets
import threading
import time
import traceback
import urllib.parse
from collections.abc import Callable
from typing import Any

PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION, *LEGACY_PROTOCOL_VERSIONS)

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
UNSUPPORTED_PROTOCOL_VERSION = -32022

MAX_REQUEST_SIZE = 16 * 1024 * 1024

# Headers of requests forwarded by a proxy or tunnel. Cloudflare ends requests without a response
# after 100 to 125 seconds, the Claude apps wait about 60 seconds for a tool: long tool calls
# continue in the background, see `GET_RESULT_TOOL`.
PROXY_HEADERS = ("cf-ray", "cdn-loop", "x-forwarded-for", "forwarded", "via")
# Pages allowed to send requests (the `Origin` header), besides this device: the Claude apps.
ALLOWED_ORIGIN_DOMAINS = ("claude.ai", "claude.com", "anthropic.com")
# Requests kept for the interface (method, status, client: no URL, the token may be part of it).
RECENT_REQUESTS = 20
GET_RESULT_TOOL = "get_tool_result"
# Tool calls continuing in the background that are kept (oldest results are dropped).
MAX_PENDING_CALLS = 32


class ToolError(Exception):
    """An error reported to the client as a tool result (``isError``), not a protocol error."""


class Tool:
    __slots__ = (
        "name",
        "description",
        "input_schema",
        "function",
        "annotations",
    )

    def __init__(
            self,
            name: str,
            description: str,
            input_schema: dict[str, Any],
            function: Callable[[dict[str, Any]], list[dict[str, Any]]],
            *,
            annotations: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        # Takes the arguments, returns a list of MCP content blocks.
        self.function = function
        self.annotations = annotations

    def as_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.annotations:
            result["annotations"] = self.annotations
        return result


class _RPCError(Exception):
    def __init__(self, code: int, message: str, *, http_status: int = 200, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data


def _check_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
    schema = tool.input_schema
    properties = schema.get("properties", {})
    for key in schema.get("required", ()):
        if key not in arguments:
            raise _RPCError(INVALID_PARAMS, "Missing argument {!r} for tool {!r}".format(key, tool.name))
    types = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    for key, value in arguments.items():
        if key not in properties:
            if schema.get("additionalProperties", True) is False:
                raise _RPCError(INVALID_PARAMS, "Unknown argument {!r} for tool {!r}".format(key, tool.name))
            continue
        expected = types.get(properties[key].get("type", ""))
        if expected is None or value is None:
            continue
        # `bool` is a sub-class of `int`.
        if isinstance(value, bool) and expected is not bool and bool not in (
                expected if isinstance(expected, tuple) else (expected,)):
            raise _RPCError(INVALID_PARAMS, "Argument {!r} must be a {:s}".format(key, properties[key]["type"]))
        if not isinstance(value, expected):
            raise _RPCError(INVALID_PARAMS, "Argument {!r} must be a {:s}".format(key, properties[key]["type"]))


def _header_decode(value: str) -> str:
    """Decode the Base64 sentinel encoding of MCP headers (``=?base64?...?=``)."""
    if value.startswith("=?base64?") and value.endswith("?="):
        return base64.b64decode(value[9:-2]).decode("utf-8")
    return value


class Server:
    """
    MCP server on a background thread.

    :arg executor: Runs a function (without arguments) on the main thread and returns its
       result, arguments: ``(function, timeout)``, raises ``TimeoutError`` when the main thread
       didn't start it in time.
    :arg token: Required from clients, as ``Authorization: Bearer <token>`` header or as the
       last path component of the URL (``/mcp/<token>``, for clients that can't set headers).
    :arg proxy_response_timeout: Seconds a request through a proxy or tunnel waits for a tool,
       the tool then continues in the background and its result is returned by the
       ``get_tool_result`` tool (requests without a response for a while are ended by proxies).
    """

    def __init__(
            self,
            *,
            host: str,
            port: int,
            token: str,
            tools: list[Tool],
            executor: Callable[[Callable[[], Any], float], Any],
            server_info: dict[str, str],
            instructions: str = "",
            tool_timeout: float = 600.0,
            proxy_response_timeout: float = 50.0,
            log: Callable[[str], None] = print,
    ) -> None:
        if not token:
            raise ValueError("A token is required")
        self.host = host
        self.port = port
        self._token = token
        self._tools = {tool.name: tool for tool in tools}
        self._tools[GET_RESULT_TOOL] = Tool(
            GET_RESULT_TOOL,
            (
                "Get the result of a tool call that continued in Blender because it took long "
                "(the call returned a job_id). Waits up to {:.0f} seconds, call again while it's "
                "still running."
            ).format(proxy_response_timeout),
            {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Job of the tool call"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
            # Handled by the server (not on the main thread), see `_get_result`.
            lambda arguments: [],
            annotations={"readOnlyHint": True, "openWorldHint": False},
        )
        self._executor = executor
        self._server_info = server_info
        self._instructions = instructions
        self._tool_timeout = tool_timeout
        self._proxy_response_timeout = proxy_response_timeout
        self._log = log
        # Tool calls continuing in the background: job identifier -> call.
        self._pending: dict[str, _PendingCall] = {}
        self._pending_lock = threading.Lock()
        self._recent: collections.deque[dict[str, Any]] = collections.deque(maxlen=RECENT_REQUESTS)
        # Requests with this header (lower-case name, value) aren't kept in `recent_requests`, e.g.
        # the tunnel's check of the public address.
        self.unlisted_header: tuple[str, str] | None = None
        self._httpd: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------------------
    # Life-time

    def start(self) -> None:
        server = self

        class Handler(_RequestHandler):
            mcp = server

        self._httpd = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        # The actual port (when zero was requested).
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="MCPServer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Replace the token (clients using the previous one aren't authorized anymore)."""
        if not value:
            raise ValueError("A token is required")
        self._token = value

    def recent_requests(self) -> list[dict[str, Any]]:
        """
        The last requests, oldest first: ``time`` (seconds since the epoch), ``method`` (HTTP),
        ``rpc`` (JSON-RPC method, with the tool name), ``status``, ``error`` (message of an error
        response), ``proxied``, ``client``.
        """
        return list(self._recent)

    def record_request(self, method: str, rpc: str, status: int, headers: dict[str, str], error: str = "") -> None:
        if self.unlisted_header is not None and headers.get(self.unlisted_header[0]) == self.unlisted_header[1]:
            return
        self._recent.append({
            "time": time.time(),
            "method": method,
            "rpc": rpc,
            "status": status,
            "error": error[:200],
            "proxied": any(name in headers for name in PROXY_HEADERS),
            "client": headers.get("user-agent", "")[:80],
        })

    # -------------------------------------------------------------------------
    # Authentication

    def check_path(self, path: str, authorization: str | None) -> bool | None:
        """
        :return: None when the path isn't the MCP end-point, otherwise whether the request
           is authorized.
        """
        parts = [part for part in urllib.parse.urlsplit(path).path.split("/") if part]
        if not parts or parts[0] != "mcp" or len(parts) > 2:
            return None
        if len(parts) == 2:
            token = urllib.parse.unquote(parts[1])
        elif authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        else:
            return False
        return hmac.compare_digest(token.encode("utf-8"), self._token.encode("utf-8"))

    # -------------------------------------------------------------------------
    # Messages

    def handle_message(self, message: Any, headers: dict[str, str]) -> tuple[int, Any]:
        """
        Handle one JSON-RPC message.

        :arg headers: Request headers (lower-case names).
        :return: HTTP status and the JSON-RPC response (None for notifications).
        """
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
            if isinstance(message, dict) and ("result" in message or "error" in message):
                # A response from the client: this server doesn't send requests.
                return 202, None
            return 400, _error_response(None, INVALID_REQUEST, "Invalid JSON-RPC request")

        method = message["method"]
        params = message.get("params") or {}
        is_notification = "id" not in message
        request_id = message.get("id")

        if is_notification:
            # `notifications/initialized`, `notifications/cancelled` ... nothing to do.
            return 202, None

        if not isinstance(params, dict):
            return 400, _error_response(request_id, INVALID_PARAMS, "Invalid parameters")

        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        modern_version = meta.get(META_PROTOCOL_VERSION)
        wait = self._proxy_response_timeout if any(name in headers for name in PROXY_HEADERS) else None
        try:
            if modern_version is not None:
                self._check_modern_headers(method, params, modern_version, headers)
                result = self._dispatch_modern(method, params, wait)
                result.setdefault("resultType", "complete")
            else:
                self._check_legacy_headers(method, headers)
                result = self._dispatch_legacy(method, params, wait)
        except _RPCError as ex:
            return ex.http_status, _error_response(request_id, ex.code, ex.message, ex.data)
        except Exception as ex:
            self._log("MCP: internal error: {:s}".format(traceback.format_exc()))
            return 500, _error_response(request_id, INTERNAL_ERROR, "Internal error: {!s}".format(ex))
        return 200, {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _check_modern_headers(
            self, method: str, params: dict[str, Any], version: Any, headers: dict[str, str],
    ) -> None:
        header_version = headers.get("mcp-protocol-version")
        if header_version is None:
            raise _RPCError(HEADER_MISMATCH, "Missing header: MCP-Protocol-Version", http_status=400)
        if header_version != version:
            raise _RPCError(
                HEADER_MISMATCH,
                "Header mismatch: MCP-Protocol-Version header value {!r} does not match body value {!r}".format(
                    header_version, version),
                http_status=400,
            )
        if version != PROTOCOL_VERSION:
            raise _RPCError(
                UNSUPPORTED_PROTOCOL_VERSION,
                "Unsupported protocol version",
                http_status=400,
                data={"supported": list(SUPPORTED_PROTOCOL_VERSIONS), "requested": version},
            )
        header_method = headers.get("mcp-method")
        if header_method is None:
            raise _RPCError(HEADER_MISMATCH, "Missing header: Mcp-Method", http_status=400)
        if header_method != method:
            raise _RPCError(
                HEADER_MISMATCH,
                "Header mismatch: Mcp-Method header value {!r} does not match body value {!r}".format(
                    header_method, method),
                http_status=400,
            )
        if method in {"tools/call", "prompts/get", "resources/read"}:
            body_name = params.get("uri") if method == "resources/read" else params.get("name")
            header_name = headers.get("mcp-name")
            if header_name is None:
                raise _RPCError(HEADER_MISMATCH, "Missing header: Mcp-Name", http_status=400)
            try:
                header_name = _header_decode(header_name)
            except (ValueError, UnicodeDecodeError):
                raise _RPCError(HEADER_MISMATCH, "Invalid header: Mcp-Name", http_status=400)
            if header_name != body_name:
                raise _RPCError(
                    HEADER_MISMATCH,
                    "Header mismatch: Mcp-Name header value {!r} does not match body value {!r}".format(
                        header_name, body_name),
                    http_status=400,
                )

    def _check_legacy_headers(self, method: str, headers: dict[str, str]) -> None:
        if method == "initialize":
            return
        # Absent for clients before 2025-06-18.
        version = headers.get("mcp-protocol-version")
        if version is not None and version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise _RPCError(
                INVALID_REQUEST,
                "Unsupported protocol version: {!r}, supported: {:s}".format(
                    version, ", ".join(SUPPORTED_PROTOCOL_VERSIONS)),
                http_status=400,
            )

    def _capabilities(self) -> dict[str, Any]:
        return {"tools": {"listChanged": False}}

    def _dispatch_modern(self, method: str, params: dict[str, Any], wait: float | None) -> dict[str, Any]:
        if method == "server/discover":
            result: dict[str, Any] = {
                "supportedVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
                "capabilities": self._capabilities(),
                "_meta": {META_SERVER_INFO: self._server_info},
            }
            if self._instructions:
                result["instructions"] = self._instructions
            return result
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.as_dict() for tool in self._tools.values()]}
        if method == "tools/call":
            return self._call_tool(params, wait)
        raise _RPCError(METHOD_NOT_FOUND, "Method not found: {!r}".format(method), http_status=404)

    def _dispatch_legacy(self, method: str, params: dict[str, Any], wait: float | None) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in LEGACY_PROTOCOL_VERSIONS else LEGACY_PROTOCOL_VERSIONS[0]
            result: dict[str, Any] = {
                "protocolVersion": version,
                "capabilities": self._capabilities(),
                "serverInfo": self._server_info,
            }
            if self._instructions:
                result["instructions"] = self._instructions
            return result
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.as_dict() for tool in self._tools.values()]}
        if method == "tools/call":
            return self._call_tool(params, wait)
        if method in {"resources/list", "resources/templates/list", "prompts/list"}:
            # Not advertised, answer anyway for clients that ask.
            return {method.split("/")[0] if method != "resources/templates/list" else "resourceTemplates": []}
        raise _RPCError(METHOD_NOT_FOUND, "Method not found: {!r}".format(method))

    def _call_tool(self, params: dict[str, Any], wait: float | None = None) -> dict[str, Any]:
        """
        :arg wait: Seconds to wait for the result, then the tool continues in the background
           (``get_tool_result``), no limit when None.
        """
        name = params.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise _RPCError(INVALID_PARAMS, "Unknown tool: {!r}".format(name))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _RPCError(INVALID_PARAMS, "Invalid tool arguments")
        _check_arguments(tool, arguments)
        if name == GET_RESULT_TOOL:
            return self._get_result(arguments["job_id"], self._proxy_response_timeout if wait is None else wait)
        if wait is None:
            return self._run_tool(tool, arguments)

        call = _PendingCall(name)
        thread = threading.Thread(target=call.run, args=(lambda: self._run_tool(tool, arguments),),
                                  name="MCPTool", daemon=True)
        thread.start()
        if call.done.wait(wait):
            return call.result
        job_id = secrets.token_hex(6)
        with self._pending_lock:
            self._pending[job_id] = call
            # Drop the oldest calls (finished first).
            while len(self._pending) > MAX_PENDING_CALLS:
                finished = [key for key, value in self._pending.items() if value.done.is_set()]
                del self._pending[(finished or list(self._pending))[0]]
        return _still_running(name, job_id, wait)

    def _get_result(self, job_id: str, wait: float) -> dict[str, Any]:
        with self._pending_lock:
            call = self._pending.get(job_id)
        if call is None:
            return {"content": [{"type": "text", "text": "Unknown job_id {!r} (its result was already returned, "
                                 "or it's too old)".format(job_id)}], "isError": True}
        if not call.done.wait(wait):
            return _still_running(call.name, job_id, time.monotonic() - call.started)
        with self._pending_lock:
            self._pending.pop(job_id, None)
        return call.result

    def _run_tool(self, tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            content = self._executor(lambda: tool.function(arguments), self._tool_timeout)
        except ToolError as ex:
            return {"content": [{"type": "text", "text": str(ex)}], "isError": True}
        except TimeoutError:
            return {
                "content": [{"type": "text", "text": (
                    "Timeout: Blender didn't run the tool in time "
                    "(the application may be in the background or busy)"
                )}],
                "isError": True,
            }
        except Exception:
            return {"content": [{"type": "text", "text": traceback.format_exc()}], "isError": True}
        return {"content": content, "isError": False}


class _PendingCall:
    """A tool call that may continue after its request returned."""
    __slots__ = ("name", "started", "done", "result")

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = time.monotonic()
        self.done = threading.Event()
        self.result: dict[str, Any] = {}

    def run(self, function: Callable[[], dict[str, Any]]) -> None:
        try:
            self.result = function()
        except BaseException:
            self.result = {"content": [{"type": "text", "text": traceback.format_exc()}], "isError": True}
        self.done.set()


def _still_running(name: str, job_id: str, elapsed: float) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": (
            "The tool {!r} is still running in Blender ({:.0f} seconds so far), it continues in the "
            "background. Call the tool {!r} with job_id {!r} to get its result."
        ).format(name, elapsed, GET_RESULT_TOOL, job_id)}],
        "isError": False,
    }


def _error_message(payload: Any) -> str:
    """Message of an error response (JSON-RPC or not), for the requests log."""
    if isinstance(payload, list):
        return "; ".join(filter(None, (_error_message(item) for item in payload)))[:200]
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message", ""))
    return str(error) if isinstance(error, str) else ""


def _describe(message: Any) -> str:
    """JSON-RPC method of a message (with the tool's name), for the requests log."""
    if isinstance(message, list):
        return "batch: " + ", ".join(_describe(item) for item in message[:4])
    if not isinstance(message, dict):
        return "?"
    method = message.get("method")
    if not isinstance(method, str):
        return "response" if "result" in message or "error" in message else "?"
    params = message.get("params")
    if method == "tools/call" and isinstance(params, dict) and isinstance(params.get("name"), str):
        return "tools/call " + params["name"][:60]
    return method[:60]


def _error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    response: dict[str, Any] = {"jsonrpc": "2.0", "error": error}
    # Errors without an identifier (e.g. parse errors) have no `id`.
    if request_id is not None:
        response["id"] = request_id
    return response


class _RequestHandler(http.server.BaseHTTPRequestHandler):
    mcp: Server
    protocol_version = "HTTP/1.1"
    server_version = "BlenderMCP/1.0"
    # JSON-RPC method of the current request & whether its body was read (see `parse_request`).
    _rpc = ""
    _body_read = False

    def log_message(self, format: str, *args: Any) -> None:
        # Don't log every request.
        pass

    def parse_request(self) -> bool:
        # Description of the request for `Server.recent_requests` (one handler serves all requests
        # of a connection).
        self._rpc = ""
        self._body_read = False
        return super().parse_request()

    def _has_body(self) -> bool:
        return bool(self.headers.get("Transfer-Encoding")) or self.headers.get("Content-Length", "0").strip() not in {"", "0"}

    def _send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        self.mcp.record_request(self.command, self._rpc, status, self._headers(), _error_message(payload))
        if not self._body_read and self._has_body():
            # The body that wasn't read would be taken as the next request of the connection (which
            # a tunnel shares between clients).
            extra_headers = {**(extra_headers or {}), "Connection": "close"}
            self.close_connection = True
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self) -> bytes | None:
        """Reads the request body (with a length or chunked), None when it's invalid or too large."""
        body = self._read_body_data()
        # A partly read body (too large or invalid) leaves the connection unusable.
        self._body_read = body is not None
        return body

    def _read_body_data(self) -> bytes | None:
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            # Sent by some proxies & tunnels.
            chunks = []
            size = 0
            while True:
                line = self.rfile.readline(1024)
                try:
                    chunk_size = int(line.split(b";", 1)[0].strip(), 16)
                except ValueError:
                    return None
                if chunk_size == 0:
                    # Trailers end with an empty line.
                    while self.rfile.readline(1024).strip():
                        pass
                    return b"".join(chunks)
                size += chunk_size
                if size > MAX_REQUEST_SIZE:
                    return None
                chunks.append(self.rfile.read(chunk_size))
                self.rfile.readline(1024)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length < 0 or length > MAX_REQUEST_SIZE:
            return None
        return self.rfile.read(length)

    def _check_request(self) -> bool:
        """Checks the end-point, authentication and origin, sends an error response on failure."""
        authorized = self.mcp.check_path(self.path, self.headers.get("Authorization"))
        if authorized is None:
            self._send_json(404, {"error": "Not found, the MCP end-point is /mcp"})
            return False
        if not authorized:
            self._send_json(401, {"error": "Unauthorized: invalid or missing token"},
                            {"WWW-Authenticate": "Bearer"})
            return False
        # Protection against DNS rebinding (a page of another site reaching this device's server):
        # browsers send the origin of the page. Requests through a tunnel come from the internet
        # (the token is required anyway), the Claude apps may send their own origin.
        origin = self.headers.get("Origin")
        if origin is not None and origin != "null" and not self._is_proxied():
            host = (urllib.parse.urlsplit(origin).hostname or "").lower()
            allowed = host in {"localhost", "127.0.0.1", "::1"} or any(
                host == domain or host.endswith("." + domain) for domain in ALLOWED_ORIGIN_DOMAINS)
            if not allowed:
                self._send_json(403, _error_response(None, INVALID_REQUEST, "Forbidden origin"))
                return False
        return True

    def _is_proxied(self) -> bool:
        return any(self.headers.get(name) is not None for name in PROXY_HEADERS)

    def _headers(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.headers.items()}

    def do_GET(self) -> None:
        if not self._check_request():
            return
        # No server initiated stream.
        self._send_json(405, None, {"Allow": "POST"})

    # Some clients probe the end-point first, don't reply "501 Not Implemented" (the default).
    do_HEAD = do_GET

    def do_OPTIONS(self) -> None:
        # No cross-origin requests (CORS): browsers only get the allowed methods.
        if self.mcp.check_path(self.path, None) is None:
            self._send_json(404, None)
            return
        self._send_json(204, None, {"Allow": "GET, HEAD, POST, DELETE, OPTIONS"})

    def do_DELETE(self) -> None:
        if not self._check_request():
            return
        # No sessions.
        self._send_json(405, None, {"Allow": "POST"})

    def do_POST(self) -> None:
        if not self._check_request():
            return
        body = self._read_body()
        if body is None:
            self._send_json(413, _error_response(None, INVALID_REQUEST, "Invalid or too large request"),
                            {"Connection": "close"})
            self.close_connection = True
            return
        try:
            message = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, _error_response(None, PARSE_ERROR, "Parse error"))
            return

        headers = self._headers()
        self._rpc = _describe(message)
        if isinstance(message, list):
            # JSON-RPC batch (protocol version 2025-03-26).
            responses = []
            for item in message:
                _status, response = self.mcp.handle_message(item, headers)
                if response is not None:
                    responses.append(response)
            self._send_json(200 if responses else 202, responses or None)
            return

        status, response = self.mcp.handle_message(message, headers)
        self._send_json(status, response)
