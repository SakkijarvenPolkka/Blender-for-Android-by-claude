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
import hmac
import http.server
import json
import threading
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
       result, arguments: ``(function, timeout)``.
    :arg token: Required from clients, as ``Authorization: Bearer <token>`` header or as the
       last path component of the URL (``/mcp/<token>``, for clients that can't set headers).
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
            log: Callable[[str], None] = print,
    ) -> None:
        if not token:
            raise ValueError("A token is required")
        self.host = host
        self.port = port
        self._token = token
        self._tools = {tool.name: tool for tool in tools}
        self._executor = executor
        self._server_info = server_info
        self._instructions = instructions
        self._tool_timeout = tool_timeout
        self._log = log
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
        try:
            if modern_version is not None:
                self._check_modern_headers(method, params, modern_version, headers)
                result = self._dispatch_modern(method, params)
                result.setdefault("resultType", "complete")
            else:
                self._check_legacy_headers(method, headers)
                result = self._dispatch_legacy(method, params)
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

    def _dispatch_modern(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
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
            return self._call_tool(params)
        raise _RPCError(METHOD_NOT_FOUND, "Method not found: {!r}".format(method), http_status=404)

    def _dispatch_legacy(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
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
            return self._call_tool(params)
        if method in {"resources/list", "resources/templates/list", "prompts/list"}:
            # Not advertised, answer anyway for clients that ask.
            return {method.split("/")[0] if method != "resources/templates/list" else "resourceTemplates": []}
        raise _RPCError(METHOD_NOT_FOUND, "Method not found: {!r}".format(method))

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            raise _RPCError(INVALID_PARAMS, "Unknown tool: {!r}".format(name))
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise _RPCError(INVALID_PARAMS, "Invalid tool arguments")
        _check_arguments(tool, arguments)

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

    def log_message(self, format: str, *args: Any) -> None:
        # Don't log every request.
        pass

    def _send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
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
        # Protection against DNS rebinding: browsers send the origin of the page.
        origin = self.headers.get("Origin")
        if origin is not None and origin != "null":
            host = urllib.parse.urlsplit(origin).hostname or ""
            if host not in {"localhost", "127.0.0.1", "::1"}:
                self._send_json(403, _error_response(None, INVALID_REQUEST, "Forbidden origin"))
                return False
        return True

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

        headers = {key.lower(): value for key, value in self.headers.items()}
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
