# SPDX-License-Identifier: GPL-2.0-or-later
"""
Tests of the parts of the MCP server add-on that don't need Blender, on the build machine:

- ``protocol``: authentication (token as header or in the path, token replacement), origins,
  the requests log, tool calls through a proxy continuing in the background.
- ``tunnel``: running cloudflared, with a stand-in program printing cloudflared's messages.

  python3 tests/mcp/test_mcp_host.py
"""

import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import urllib.request

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDON_DIR = os.path.join(REPO_DIR, "blender", "overlay", "scripts", "addons_core", "mcp_server")


def _load(name):
    spec = importlib.util.spec_from_file_location("mcp_server_" + name, os.path.join(ADDON_DIR, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = _load("protocol")
tunnel = _load("tunnel")

# cloudflared's messages (2026.11.0), see `cmd/cloudflared/tunnel/quick_tunnel.go`, `cliutil/logger.go`
# and `orchestration/orchestrator.go`. The mode comes from `FAKE_MODE`, runs are counted in `HOME`.
FAKE_CLOUDFLARED = textwrap.dedent(r"""
    import json, os, signal, sys, time
    home = os.environ["HOME"]
    with open(os.path.join(home, "invocation.json"), "w") as fh:
        json.dump({"argv": sys.argv[1:], "token": os.environ.get("TUNNEL_TOKEN")}, fh)
    runs_path = os.path.join(home, "runs")
    run = (int(open(runs_path).read()) if os.path.exists(runs_path) else 0) + 1
    with open(runs_path, "w") as fh:
        fh.write(str(run))
    mode = os.environ.get("FAKE_MODE", "quick")

    def log(level, message):
        print("2026-11-15T08:00:00Z {:s} {:s}".format(level, message), flush=True)

    signal.signal(signal.SIGTERM, lambda *args: (log("INF", "Initiating graceful shutdown"), sys.exit(0)))

    def quick(host):
        log("INF", "Thank you for trying Cloudflare Tunnel. ... (https://www.cloudflare.com/website-terms/) ... "
                   "https://developers.cloudflare.com/cloudflare-one/connections/connect-apps")
        log("INF", "Requesting new quick Tunnel on trycloudflare.com...")
        log("INF", "+--------------------------------------------------------------------------------------------+")
        log("INF", "|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |")
        log("INF", "|  https://{:s}                                      |".format(host))
        log("INF", "+--------------------------------------------------------------------------------------------+")

    def configuration(service):
        config = {"ingress": [{"hostname": "blender.example.com", "originRequest": {}, "service": service},
                              {"service": "http_status:404"}], "warp-routing": {"enabled": False}}
        log("INF", "Updated to new configuration config={:s} version=1".format(json.dumps(json.dumps(config))))

    def connected():
        log("WRN", "Cannot determine default configuration path. No file [config.yml config.yaml] in [~/.cloudflared]")
        time.sleep(0.2)
        log("INF", "Registered tunnel connection connIndex=0 connection=5ab0e6c6 event=0 ip=198.41.200.13 "
                   "location=icn01 protocol=quic")

    def fail(message, code=1):
        # Errors ending cloudflared are printed by urfave/cli, without time & level.
        log("INF", "Requesting new quick Tunnel on trycloudflare.com...")
        print(message, file=sys.stderr, flush=True)
        sys.exit(code)

    if mode == "fail" or (mode == "fail-once" and run == 1):
        fail('failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp: '
             'lookup api.trycloudflare.com: no such host')
    if mode == "ratelimit":
        fail("quick tunnel provisioning failed with status 429: Too Many Requests")
    if mode == "invalid-token":
        fail("Provided Tunnel token is not valid.\nSee 'cloudflared tunnel run --help'.", 255)
    if mode in {"quick", "fail-once", "leak"}:
        quick("seasonal-deck-organisms-sf.trycloudflare.com")
    if mode == "crash":
        quick("first-address-words-ab.trycloudflare.com" if run == 1 else "second-address-words-cd.trycloudflare.com")
    if mode == "named-config":
        configuration("http://localhost:8765")
    if mode == "named-config-wrong":
        configuration("http://localhost:3000")
    connected()
    if mode == "leak":
        log("ERR", 'Request failed error="Unable to reach the origin service" '
                   'dest=https://seasonal-deck-organisms-sf.trycloudflare.com/mcp/SECRET-TOKEN-123 type=http')
        log("INF", "header Authorization: Bearer SECRET-TOKEN-123")
    if mode == "crash" and run == 1:
        time.sleep(0.3)
        log("ERR", 'Connection terminated error="there are no free edge addresses left to resolve to"')
        sys.exit(1)
    while True:
        time.sleep(0.1)
    """)


def write_fake_cloudflared(path):
    with open(path, "w") as fh:
        fh.write("#!" + sys.executable + "\n" + FAKE_CLOUDFLARED)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.server = protocol.Server(
            host="127.0.0.1", port=0, token="secret-1", tools=[],
            executor=lambda function, timeout: function(),
            server_info={"name": "test", "version": "1"}, log=lambda message: None,
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def post(self, path, headers=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "test", "version": "1"}}}).encode()
        request = urllib.request.Request(
            "http://127.0.0.1:{:d}{:s}".format(self.server.port, path), data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                     **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as ex:
            return ex.code, None

    def test_token_in_path(self):
        status, response = self.post("/mcp/secret-1")
        self.assertEqual(status, 200)
        self.assertEqual(response["result"]["serverInfo"]["name"], "test")
        self.assertEqual(self.post("/mcp/wrong")[0], 401)
        self.assertEqual(self.post("/mcp")[0], 401)
        self.assertEqual(self.post("/other/secret-1")[0], 404)

    def test_token_header(self):
        self.assertEqual(self.post("/mcp", {"Authorization": "Bearer secret-1"})[0], 200)
        self.assertEqual(self.post("/mcp", {"Authorization": "Bearer wrong"})[0], 401)

    def test_replace_token(self):
        self.server.token = "secret-2"
        self.assertEqual(self.post("/mcp/secret-1")[0], 401)
        self.assertEqual(self.post("/mcp/secret-2")[0], 200)
        with self.assertRaises(ValueError):
            self.server.token = ""

    def test_origin(self):
        # DNS rebinding protection: pages of other sites can't use the server of this device.
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "http://localhost:3000"})[0], 200)
        # The Claude apps.
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "https://claude.ai"})[0], 200)
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "https://www.claude.com"})[0], 200)
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "https://claude.ai.evil.example"})[0], 403)
        # Through a tunnel (from the internet, the token is required anyway).
        self.assertEqual(self.post("/mcp/secret-1", {"Origin": "https://other.example", "Cf-Ray": "8d1f-ICN"})[0], 200)
        self.assertEqual(self.post("/mcp/wrong", {"Origin": "https://other.example", "Cf-Ray": "8d1f-ICN"})[0], 401)

    def test_recent_requests(self):
        self.post("/mcp/secret-1", {"Cf-Ray": "8d1f-ICN", "User-Agent": "Claude-User"})
        self.post("/mcp/wrong")
        requests = self.server.recent_requests()
        self.assertEqual([(r["rpc"], r["status"], r["proxied"]) for r in requests],
                         [("initialize", 200, True), ("", 401, False)])
        self.assertEqual(requests[0]["client"], "Claude-User")
        # No URL (the token may be part of it).
        self.assertNotIn("secret-1", json.dumps(requests))

    def test_unread_body_closes_connection(self):
        # The body of a rejected request must not be taken as another request of the connection.
        smuggled = b"POST /mcp/secret-1 HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{}"
        request = (b"POST /mcp/wrong HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                   b"Content-Length: " + str(len(smuggled)).encode() + b"\r\n\r\n" + smuggled)
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=10) as sock:
            sock.sendall(request)
            data = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        self.assertEqual(data.count(b"HTTP/1.1 "), 1, data)
        self.assertIn(b"401", data.split(b"\r\n")[0])
        self.assertIn(b"Connection: close", data)

    def test_oauth_discovery_not_found(self):
        # Clients look for OAuth metadata first: none means no OAuth (the token is in the URL).
        request = urllib.request.Request("http://127.0.0.1:{:d}/.well-known/oauth-protected-resource/mcp/secret-1".format(
            self.server.port))
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(context.exception.code, 404)


class ProxiedToolCallTest(unittest.TestCase):
    """Long tool calls through a proxy (e.g. Cloudflare, 100 s limit) continue in the background."""

    def setUp(self):
        def slow(arguments):
            time.sleep(arguments["seconds"])
            return [{"type": "text", "text": "done after {:g}".format(arguments["seconds"])}]

        tool = protocol.Tool("slow", "Sleeps", {
            "type": "object", "properties": {"seconds": {"type": "number"}}, "required": ["seconds"]}, slow)
        self.server = protocol.Server(
            host="127.0.0.1", port=0, token="secret", tools=[tool],
            executor=lambda function, timeout: function(),
            server_info={"name": "test", "version": "1"}, proxy_response_timeout=0.5,
            log=lambda message: None,
        )
        self.server.start()
        self.addCleanup(self.server.stop)

    def call(self, name, arguments, proxied):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-06-18"}
        if proxied:
            headers.update({"Cf-Ray": "8d1f2c3a4b5c6d7e-ICN", "X-Forwarded-For": "203.0.113.7"})
        request = urllib.request.Request(
            "http://127.0.0.1:{:d}/mcp/secret".format(self.server.port), data=body, method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())["result"]

    def test_listed(self):
        self.assertIn(protocol.GET_RESULT_TOOL, self.server._tools)

    def test_direct_waits(self):
        result = self.call("slow", {"seconds": 1.0}, proxied=False)
        self.assertEqual(result["content"][0]["text"], "done after 1")

    def test_proxied_fast(self):
        result = self.call("slow", {"seconds": 0.0}, proxied=True)
        self.assertEqual(result["content"][0]["text"], "done after 0")

    def test_proxied_continues(self):
        result = self.call("slow", {"seconds": 1.5}, proxied=True)
        self.assertFalse(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("still running", text)
        job_id = text.split("job_id ")[1].split("'")[1]
        # Waits up to 0.5 seconds: still running, then done.
        results = [self.call(protocol.GET_RESULT_TOOL, {"job_id": job_id}, proxied=True) for _ in range(6)]
        texts = [r["content"][0]["text"] for r in results]
        self.assertIn("done after 1.5", texts, texts)
        done = texts.index("done after 1.5")
        self.assertTrue(all("still running" in t for t in texts[:done]), texts)
        # Returned once.
        self.assertTrue(results[done + 1]["isError"])
        self.assertIn("Unknown job_id", texts[done + 1])

    def test_unknown_job(self):
        result = self.call(protocol.GET_RESULT_TOOL, {"job_id": "nope"}, proxied=False)
        self.assertTrue(result["isError"])


class TunnelTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.executable = os.path.join(self.directory.name, "cloudflared")
        write_fake_cloudflared(self.executable)
        self.home = os.path.join(self.directory.name, "home")
        self.changes = 0
        self.checked = []

    def make(self, mode, *, reachable=True, **kwargs):
        os.environ["FAKE_MODE"] = mode
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)

        def on_change():
            self.changes += 1

        def check(url, stop):
            self.checked.append(url)
            return reachable

        instance = tunnel.Tunnel(executable=self.executable, local_url="http://127.0.0.1:8765",
                                 home=self.home, log=lambda message: None, on_change=on_change,
                                 check=check, retry_delays=(0.3,), **kwargs)
        self.addCleanup(instance.stop)
        return instance

    def invocation(self):
        with open(os.path.join(self.home, "invocation.json")) as fh:
            return json.load(fh)

    def runs(self):
        with open(os.path.join(self.home, "runs")) as fh:
            return int(fh.read())

    def wait_for(self, condition, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(0.05)
        return False

    def test_quick_tunnel(self):
        instance = self.make("quick")
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0), instance.log_lines())
        self.assertEqual(instance.state, tunnel.Tunnel.CONNECTED)
        self.assertEqual(instance.public_url, "https://seasonal-deck-organisms-sf.trycloudflare.com")
        self.assertTrue(instance.reachable)
        self.assertEqual(self.checked, ["https://seasonal-deck-organisms-sf.trycloudflare.com"])
        self.assertEqual(instance.error, "")
        self.assertFalse(instance.address_changed)
        self.assertGreater(self.changes, 0)
        argv = self.invocation()["argv"]
        self.assertEqual(argv[argv.index("--url") + 1], "http://127.0.0.1:8765")
        self.assertEqual(argv[argv.index("--protocol") + 1], "auto")
        self.assertIn("--no-autoupdate", argv)
        self.assertNotIn("debug", argv)
        self.assertIsNone(self.invocation()["token"])
        start = time.monotonic()
        instance.stop()
        self.assertLess(time.monotonic() - start, 10.0)
        self.assertEqual(instance.state, tunnel.Tunnel.STOPPED)

    def test_unreachable_address(self):
        instance = self.make("quick", reachable=False)
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0))
        self.assertIs(instance.reachable, False)

    def test_named_tunnel(self):
        os.environ["TUNNEL_TOKEN"] = "from-the-environment"
        self.addCleanup(os.environ.pop, "TUNNEL_TOKEN", None)
        instance = self.make("named", token=" eyJhIjoi-token ", hostname=" https://blender.example.com/ ")
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0), instance.log_lines())
        self.assertEqual(instance.public_url, "https://blender.example.com")
        invocation = self.invocation()
        self.assertEqual(invocation["token"], "eyJhIjoi-token")
        self.assertIn("run", invocation["argv"])
        self.assertNotIn("--url", invocation["argv"])
        # Not in the arguments (visible to other processes).
        self.assertFalse(any("eyJhIjoi-token" in arg for arg in invocation["argv"]))

    def test_named_tunnel_host_from_configuration(self):
        instance = self.make("named-config", token="eyJ-token")
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0), instance.log_lines())
        self.assertEqual(instance.public_url, "https://blender.example.com")
        self.assertEqual(instance.warning, "")

    def test_named_tunnel_wrong_service(self):
        instance = self.make("named-config-wrong", token="eyJ-token")
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0), instance.log_lines())
        self.assertIn("http://localhost:3000", instance.warning)
        self.assertIn("http://localhost:8765", instance.warning)

    def test_named_tunnel_without_host(self):
        instance = self.make("named", token="eyJ-token")
        instance.start()
        self.assertTrue(self.wait_for(lambda: "Registered" in " ".join(instance.log_lines())))
        # Connected, but the address isn't known (set it in the preferences).
        self.assertFalse(instance.wait_ready(timeout=1.0))
        self.assertEqual(instance.public_url, "")

    def test_private_configuration(self):
        instance = self.make("quick")
        instance.start()
        self.assertTrue(instance.wait_ready(timeout=20.0))
        argv = self.invocation()["argv"]
        config = argv[argv.index("--config") + 1]
        self.assertEqual(config, os.path.join(self.home, "config.yml"))
        with open(config) as fh:
            self.assertEqual(fh.read().strip(), "{}")
        self.assertEqual(stat.S_IMODE(os.stat(self.home).st_mode), 0o700)
        # The process is recorded (stopped when Blender ended without stopping it).
        with open(os.path.join(self.home, "cloudflared.pid")) as fh:
            self.assertEqual(int(fh.read()), instance._process.pid)
        instance.stop()
        self.assertFalse(os.path.exists(os.path.join(self.home, "cloudflared.pid")))

    def test_unsafe_home(self):
        other = os.path.join(self.directory.name, "other")
        os.mkdir(other)
        os.symlink(other, self.home)
        instance = self.make("quick")
        with self.assertRaises(OSError):
            instance.start()
        self.assertEqual(instance.state, tunnel.Tunnel.FAILED)
        self.assertIn("Unsafe", instance.error)

    @unittest.skipUnless(os.path.isdir("/proc/self"), "needs /proc")
    def test_previous_process_stopped(self):
        # cloudflared of a previous Blender (crashed): same configuration file.
        os.makedirs(self.home)
        os.environ["FAKE_MODE"] = "quick"
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)
        previous = subprocess.Popen([self.executable, "tunnel", "--config", os.path.join(self.home, "config.yml")],
                                    env={**os.environ, "HOME": self.home}, stdout=subprocess.DEVNULL)
        self.addCleanup(lambda: previous.poll() is None and previous.kill())
        with open(os.path.join(self.home, "cloudflared.pid"), "w") as fh:
            fh.write(str(previous.pid))
        instance = self.make("quick")
        instance.start()
        # Stopped (SIGTERM).
        self.assertIsNotNone(previous.wait(timeout=10.0))
        self.assertTrue(instance.wait_ready(timeout=20.0))

    def test_invalid_token(self):
        instance = self.make("invalid-token", token="not-a-token")
        instance.start()
        self.assertTrue(self.wait_for(lambda: instance.state == tunnel.Tunnel.FAILED))
        self.assertIn("Provided Tunnel token is not valid.", instance.error)
        # Not started again.
        time.sleep(1.0)
        self.assertEqual(self.runs(), 1)
        self.assertEqual(instance.retry_in, 0.0)

    def test_normalize_hostname(self):
        self.assertEqual(tunnel.normalize_hostname(" https://Blender.Example.com/mcp/ "), "blender.example.com")
        self.assertEqual(tunnel.normalize_hostname("blender.example.com:443"), "blender.example.com")
        self.assertEqual(tunnel.normalize_hostname("blender.example.com"), "blender.example.com")
        self.assertEqual(tunnel.normalize_hostname(""), "")

    def test_failure_and_retry(self):
        instance = self.make("fail-once")
        instance.start()
        self.assertTrue(self.wait_for(lambda: "failed to request quick Tunnel" in instance.error))
        # Started again.
        self.assertTrue(instance.wait_ready(timeout=20.0), instance.log_lines())
        self.assertEqual(self.runs(), 2)
        self.assertEqual(instance.error, "")
        self.assertEqual(instance.public_url, "https://seasonal-deck-organisms-sf.trycloudflare.com")
        # The first run had no address.
        self.assertFalse(instance.address_changed)

    def test_restart_changes_address(self):
        instance = self.make("crash")
        instance.start()
        self.assertTrue(self.wait_for(lambda: instance.public_url == "https://second-address-words-cd.trycloudflare.com"
                                      and instance.reachable), instance.log_lines())
        self.assertTrue(instance.address_changed)
        instance.acknowledge_address()
        self.assertFalse(instance.address_changed)
        self.assertEqual(self.checked, ["https://first-address-words-ab.trycloudflare.com",
                                        "https://second-address-words-cd.trycloudflare.com"])

    def test_rate_limited(self):
        instance = self.make("ratelimit")
        instance.start()
        self.assertTrue(self.wait_for(lambda: instance.retry_in > 0.0))
        self.assertGreater(instance.retry_in, tunnel.RATE_LIMIT_DELAY - 10.0)
        self.assertEqual(instance.state, tunnel.Tunnel.FAILED)
        self.assertIn("429", instance.error)
        # Stopping doesn't wait for the retry.
        start = time.monotonic()
        instance.stop()
        self.assertLess(time.monotonic() - start, 5.0)
        self.assertEqual(self.runs(), 1)

    def test_redaction(self):
        instance = self.make("leak")
        instance.start()
        self.assertTrue(self.wait_for(lambda: "Bearer" in " ".join(instance.log_lines())))
        text = " ".join(instance.log_lines()) + instance.error
        self.assertNotIn("SECRET-TOKEN-123", text)
        self.assertIn("/mcp/***", text)
        self.assertEqual(tunnel.redact("x token=eyJhIjoiNGQ1ZTdmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODki y"), "x token=*** y")

    def test_stop_during_check(self):
        def slow_check(url, stop):
            stop.wait(30.0)
            return False

        instance = self.make("quick")
        instance._check = slow_check
        instance.start()
        self.assertTrue(self.wait_for(lambda: instance.state == tunnel.Tunnel.CONNECTED))
        start = time.monotonic()
        instance.stop()
        self.assertLess(time.monotonic() - start, 5.0)
        self.assertIsNone(instance.reachable)

    def test_missing_executable(self):
        instance = tunnel.Tunnel(executable=os.path.join(self.directory.name, "missing"),
                                 local_url="http://127.0.0.1:8765", home=self.home, log=lambda message: None)
        with self.assertRaises(OSError):
            instance.start()
        self.assertEqual(instance.state, tunnel.Tunnel.FAILED)

    def test_find_executable(self):
        os.environ["BLENDER_CLOUDFLARED"] = self.executable
        self.addCleanup(os.environ.pop, "BLENDER_CLOUDFLARED", None)
        self.assertEqual(tunnel.find_executable(), self.executable)

    def test_url_pattern(self):
        self.assertIsNone(tunnel.QUICK_TUNNEL_URL_RE.search("https://www.cloudflare.com/website-terms/"))
        self.assertIsNone(tunnel.QUICK_TUNNEL_URL_RE.search("Requesting new quick Tunnel on trycloudflare.com..."))
        self.assertIsNone(tunnel.QUICK_TUNNEL_URL_RE.search("https://api.trycloudflare.com.evil.example/x"))
        self.assertIsNone(tunnel.QUICK_TUNNEL_URL_RE.search("lookup https://api.trycloudflare.com: no such host"))
        match = tunnel.QUICK_TUNNEL_URL_RE.search("|  https://a-b-c.trycloudflare.com   |")
        self.assertEqual(match.group(1), "https://a-b-c.trycloudflare.com")
        match = tunnel.QUICK_TUNNEL_URL_RE.search("https://seasonal-deck-organisms-sf.trycloudflare.com")
        self.assertEqual(match.group(1), "https://seasonal-deck-organisms-sf.trycloudflare.com")

    def test_check_public_url_answer(self):
        # The check accepts this server's answer only (not an error page of Cloudflare).
        server = protocol.Server(host="127.0.0.1", port=0, token="t", tools=[],
                                 executor=lambda function, timeout: function(),
                                 server_info={"name": "test", "version": "1"}, log=lambda message: None)
        server.start()
        self.addCleanup(server.stop)
        self.assertTrue(tunnel._server_answers("http://127.0.0.1:{:d}".format(server.port), timeout=5.0))
        self.assertFalse(tunnel._server_answers("http://127.0.0.1:1", timeout=5.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
