# SPDX-License-Identifier: GPL-2.0-or-later
"""
Tests of the parts of the MCP server add-on that don't need Blender, on the build machine:

- ``protocol``: authentication (token as header or in the path, token replacement).
- ``tunnel``: running cloudflared, with a stand-in program printing cloudflared's messages.

  python3 tests/mcp/test_mcp_host.py
"""

import importlib.util
import json
import os
import stat
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

# cloudflared's messages (2026.11.0), see `cmd/cloudflared/tunnel/quick_tunnel.go`.
FAKE_CLOUDFLARED = textwrap.dedent('''\
    #!{python}
    import json, os, signal, sys, time
    with open(os.path.join(os.environ["HOME"], "invocation.json"), "w") as fh:
        json.dump({{"argv": sys.argv[1:], "token": os.environ.get("TUNNEL_TOKEN")}}, fh)
    mode = os.environ.get("FAKE_MODE", "quick")
    def log(level, message):
        print("2026-11-15T08:00:00Z {{:s}} {{:s}}".format(level, message), flush=True)
    signal.signal(signal.SIGTERM, lambda *args: (log("INF", "Initiating graceful shutdown"), sys.exit(0)))
    if mode == "fail":
        log("INF", "Requesting new quick Tunnel on trycloudflare.com...")
        log("ERR", "failed to request quick Tunnel: Post \\"https://api.trycloudflare.com/tunnel\\": dial tcp: lookup api.trycloudflare.com: no such host")
        sys.exit(1)
    if mode == "quick":
        log("INF", "Thank you for trying Cloudflare Tunnel. ... (https://www.cloudflare.com/website-terms/) ... "
                   "https://developers.cloudflare.com/cloudflare-one/connections/connect-apps")
        log("INF", "Requesting new quick Tunnel on trycloudflare.com...")
        log("INF", "+--------------------------------------------------------------------------------------------+")
        log("INF", "|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |")
        log("INF", "|  https://seasonal-deck-organisms-sf.trycloudflare.com                                      |")
        log("INF", "+--------------------------------------------------------------------------------------------+")
    log("WRN", "Cannot determine default configuration path. No file [config.yml config.yaml] in [~/.cloudflared]")
    time.sleep(0.2)
    log("INF", "Registered tunnel connection connIndex=0 connection=5ab0e6c6 event=0 ip=198.41.200.13 location=icn01 protocol=quic")
    while True:
        time.sleep(0.1)
    ''')


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
        with open(self.executable, "w") as fh:
            fh.write(FAKE_CLOUDFLARED.format(python=sys.executable))
        os.chmod(self.executable, os.stat(self.executable).st_mode | stat.S_IEXEC)
        self.home = os.path.join(self.directory.name, "home")
        self.changes = 0

    def make(self, mode, **kwargs):
        os.environ["FAKE_MODE"] = mode
        self.addCleanup(os.environ.pop, "FAKE_MODE", None)

        def on_change():
            self.changes += 1

        instance = tunnel.Tunnel(executable=self.executable, local_url="http://127.0.0.1:8765",
                                 home=self.home, log=lambda message: None, on_change=on_change, **kwargs)
        self.addCleanup(instance.stop)
        return instance

    def invocation(self):
        with open(os.path.join(self.home, "invocation.json")) as fh:
            return json.load(fh)

    def test_quick_tunnel(self):
        instance = self.make("quick")
        instance.start()
        self.assertTrue(instance.wait_connected(timeout=20.0), instance.log_lines())
        self.assertEqual(instance.state, tunnel.Tunnel.CONNECTED)
        self.assertEqual(instance.public_url, "https://seasonal-deck-organisms-sf.trycloudflare.com")
        self.assertEqual(instance.error, "")
        self.assertGreater(self.changes, 0)
        invocation = self.invocation()
        self.assertIn("--url", invocation["argv"])
        self.assertEqual(invocation["argv"][invocation["argv"].index("--url") + 1], "http://127.0.0.1:8765")
        self.assertIn("--no-autoupdate", invocation["argv"])
        self.assertIsNone(invocation["token"])
        start = time.monotonic()
        instance.stop()
        self.assertLess(time.monotonic() - start, 10.0)
        self.assertEqual(instance.state, tunnel.Tunnel.STOPPED)

    def test_named_tunnel(self):
        os.environ["TUNNEL_TOKEN"] = "from-the-environment"
        self.addCleanup(os.environ.pop, "TUNNEL_TOKEN", None)
        instance = self.make("named", token="eyJhIjoi-token", hostname=" blender.example.com ")
        instance.start()
        self.assertTrue(instance.wait_connected(timeout=20.0), instance.log_lines())
        self.assertEqual(instance.public_url, "https://blender.example.com")
        invocation = self.invocation()
        self.assertEqual(invocation["token"], "eyJhIjoi-token")
        self.assertIn("run", invocation["argv"])
        self.assertNotIn("--url", invocation["argv"])
        # Not in the arguments (visible to other processes).
        self.assertFalse(any("eyJhIjoi-token" in arg for arg in invocation["argv"]))

    def test_failure(self):
        instance = self.make("fail")
        instance.start()
        self.assertFalse(instance.wait_connected(timeout=20.0))
        self.assertEqual(instance.state, tunnel.Tunnel.FAILED)
        self.assertIn("failed to request quick Tunnel", instance.error)
        self.assertEqual(instance.public_url, "")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
