# SPDX-License-Identifier: GPL-2.0-or-later
"""
Tests of the MCP server add-on's public address handling (Claude app connectors) without Blender:
``bpy`` is replaced by a minimal stand-in, cloudflared by a program printing its messages.

  python3 tests/mcp/test_mcp_addon.py
"""

import importlib
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDONS_DIR = os.path.join(REPO_DIR, "blender", "overlay", "scripts", "addons_core")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_mcp_host import write_fake_cloudflared  # noqa: E402


def _install_fake_bpy():
    """Just what the add-on uses at import time & in its interface code."""
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(
        AddonPreferences=object, Operator=object, Panel=object,
        Context=object, UILayout=object, Object=object, Image=object,
    )
    bpy.props = types.ModuleType("bpy.props")
    for name in ("BoolProperty", "EnumProperty", "IntProperty", "StringProperty"):
        setattr(bpy.props, name, lambda **kwargs: kwargs)

    class Timers:
        def __init__(self):
            self.registered = []

        def register(self, function, **kwargs):
            self.registered.append(function)

        def is_registered(self, function):
            return function in self.registered

        def unregister(self, function):
            self.registered.remove(function)

    bpy.app = types.SimpleNamespace(background=False, version_string="5.2.2", timers=Timers())
    def user_resource(resource_type, *, path="", create=False):
        directory = os.path.join(tempfile.gettempdir(), "blender_user_" + resource_type.lower(), path)
        if create:
            os.makedirs(directory, exist_ok=True)
        return directory

    bpy.utils = types.SimpleNamespace(register_class=lambda cls: None, unregister_class=lambda cls: None,
                                      user_resource=user_resource)
    bpy.context = types.SimpleNamespace(window_manager=types.SimpleNamespace(windows=[], clipboard=""))
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = bpy.props
    sys.modules["mathutils"] = types.ModuleType("mathutils")
    return bpy


class Layout:
    """Records what the interface code draws."""

    def __init__(self, record):
        self.record = record
        self.enabled = True

    def column(self, **kwargs):
        return Layout(self.record)

    row = box = column

    def label(self, *, text="", icon='NONE'):
        self.record.append(("label", text))

    def prop(self, data, name, **kwargs):
        self.record.append(("prop", name))

    def operator(self, name, **kwargs):
        self.record.append(("operator", name))


class Preferences:
    port = 0
    allow_network = False
    token = "addon-token"
    auto_start = False
    public_access = 'NONE'
    tunnel_token = ""
    tunnel_hostname = ""
    custom_public_url = ""


class AddonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bpy = _install_fake_bpy()
        sys.path.insert(0, ADDONS_DIR)
        cls.addon = importlib.import_module("mcp_server")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        executable = os.path.join(self.directory.name, "cloudflared")
        write_fake_cloudflared(executable)
        # No requests to the internet: the public address is "checked".
        check = self.addon.tunnel.check_public_url
        self.addon.tunnel.check_public_url = lambda url, **kwargs: True
        self.addCleanup(setattr, self.addon.tunnel, "check_public_url", check)
        environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(environ)))
        os.environ["BLENDER_CLOUDFLARED"] = executable
        os.environ["FAKE_MODE"] = "quick"
        # cloudflared's home (`_tunnel_home`).
        tempfile.tempdir = self.directory.name
        self.addCleanup(setattr, tempfile, "tempdir", None)
        self.addCleanup(self.addon.stop)
        self.preferences = Preferences()

    def draw(self):
        record = []
        self.addon._draw_settings(Layout(record), self.preferences)
        return record

    def test_off(self):
        self.assertEqual(self.addon._start_from_preferences(self.preferences), "")
        self.assertIsNotNone(self.addon._server)
        self.assertIsNone(self.addon._tunnel)
        self.assertEqual(self.addon.connector_url(self.preferences.token), "")
        self.assertNotIn(("operator", "mcp.copy_connector_url"), self.draw())

    def test_quick_tunnel(self):
        self.preferences.public_access = 'QUICK'
        self.assertEqual(self.addon._start_from_preferences(self.preferences), "")
        self.assertTrue(self.addon._tunnel.wait_ready(timeout=20.0))
        # Forwards to the server's port.
        self.assertEqual(self.addon._tunnel.local_url, "http://127.0.0.1:{:d}".format(self.addon._server.port))
        self.assertEqual(self.addon.connector_url("addon-token"),
                         "https://seasonal-deck-organisms-sf.trycloudflare.com/mcp/addon-token")
        record = self.draw()
        self.assertIn(("label", "Ready"), record)
        self.assertIn(("operator", "mcp.copy_connector_url"), record)
        self.assertIn(("label", "seasonal-deck-organisms-sf.trycloudflare.com/mcp/..."), record)
        # The token isn't shown.
        self.assertFalse(any("addon-token" in str(item) for item in record))
        # The interface is redrawn from the main thread (timer).
        self.assertTrue(self.addon._redraw_needed)
        self.addon._timer()
        self.assertFalse(self.addon._redraw_needed)

        # Requests from the internet are shown (e.g. whether Claude connected).
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        request = urllib.request.Request(
            "http://127.0.0.1:{:d}/mcp/addon-token".format(self.addon._server.port), data=body, method="POST",
            headers={"Content-Type": "application/json", "Cf-Ray": "8d1f-ICN"})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
        record = self.draw()
        self.assertIn(("label", "Requests from the internet:"), record)
        self.assertTrue(any(item[1].endswith("tools/list  200") for item in record), record)

        # Copy the connector URL.
        operator = self.addon.MCP_OT_copy_connector_url()
        operator.report = lambda kind, message: None
        context = types.SimpleNamespace(window_manager=types.SimpleNamespace(clipboard=""))
        self.addon._preferences = lambda: self.preferences
        self.assertEqual(operator.execute(context), {'FINISHED'})
        self.assertEqual(context.window_manager.clipboard,
                         "https://seasonal-deck-organisms-sf.trycloudflare.com/mcp/addon-token")

        # A new token keeps the tunnel.
        tunnel = self.addon._tunnel
        self.addon._server.token = "other-token"
        self.assertIs(self.addon._tunnel, tunnel)
        self.addon.stop()
        self.assertIsNone(self.addon._tunnel)
        self.assertEqual(tunnel.state, tunnel.STOPPED)

    def test_token_tunnel(self):
        self.preferences.public_access = 'TOKEN'
        self.assertIn("token", self.addon._start_from_preferences(self.preferences))
        # The server runs anyway.
        self.assertIsNotNone(self.addon._server)
        self.preferences.tunnel_token = " eyJ-token "
        self.preferences.tunnel_hostname = "blender.example.com"
        os.environ["FAKE_MODE"] = "named"
        self.assertEqual(self.addon._start_public_access(self.preferences), "")
        self.assertTrue(self.addon._tunnel.wait_ready(timeout=20.0))
        self.assertEqual(self.addon.connector_url("t"), "https://blender.example.com/mcp/t")

    def test_custom_url(self):
        self.preferences.public_access = 'CUSTOM'
        self.preferences.custom_public_url = "http://insecure.example.com"
        self.assertIn("https://", self.addon._start_from_preferences(self.preferences))
        self.preferences.custom_public_url = " https://phone.example.ts.net/mcp/ "
        self.assertEqual(self.addon._start_public_access(self.preferences), "")
        self.assertEqual(self.addon.connector_url("t"), "https://phone.example.ts.net/mcp/t")
        self.assertIn(("operator", "mcp.copy_connector_url"), self.draw())
        self.addon.stop()
        self.assertEqual(self.addon.connector_url("t"), "")

    def test_custom_url_checks(self):
        check = self.addon.custom_public_url
        self.assertEqual(check("https://Phone.example.ts.net/"), ("https://phone.example.ts.net", ""))
        self.assertEqual(check("https://example.com/blender/mcp"), ("https://example.com/blender", ""))
        self.assertEqual(check("https://example.com:443"), ("https://example.com", ""))
        self.assertIn("443", check("https://phone.example.ts.net:8443")[1])
        self.assertIn("https://", check("http://example.com")[1])
        self.assertIn("host name", check("https://localhost")[1])
        self.assertIn("query", check("https://example.com/?token=1")[1])
        self.assertTrue(check("https://example.com:99999")[1])

    def test_failing_tunnel(self):
        self.preferences.public_access = 'QUICK'
        os.environ["FAKE_MODE"] = "fail"
        self.assertEqual(self.addon._start_from_preferences(self.preferences), "")
        self.assertFalse(self.addon._tunnel.wait_ready(timeout=2.0))
        record = self.draw()
        self.assertIn(("label", "Tunnel stopped, starting again soon"), record)
        self.assertTrue(any("failed to request quick Tunnel" in str(item) for item in record), record)
        self.assertEqual(self.addon.connector_url("t"), "")

    def test_executor(self):
        executor = self.addon.tools.MainThreadExecutor()
        results = []

        def call(function, timeout):
            try:
                results.append(executor(function, timeout))
            except TimeoutError:
                results.append("timeout")

        # Runs longer than the timeout once started (e.g. a long render): the result is returned.
        thread = threading.Thread(target=call, args=(lambda: time.sleep(0.5) or "done", 0.3))
        thread.start()
        time.sleep(0.1)
        executor.process()
        thread.join(timeout=10.0)
        self.assertEqual(results, ["done"])
        # Not started in time: not run anymore.
        ran = []
        call(lambda: ran.append(1), 0.1)
        executor.process()
        self.assertEqual(results[-1], "timeout")
        self.assertEqual(ran, [])

    def test_serve_forever_arguments(self):
        with self.assertRaises(ValueError):
            self.addon.serve_forever(port=0, token="t", public='TOKEN')
        with self.assertRaises(ValueError):
            self.addon.serve_forever(port=0, token="t", public='quick')
        self.assertIsNone(self.addon._server)

    def test_missing_cloudflared(self):
        self.preferences.public_access = 'QUICK'
        os.environ["BLENDER_CLOUDFLARED"] = os.path.join(self.directory.name, "missing")
        empty = os.path.join(self.directory.name, "empty")
        os.mkdir(empty)
        os.environ["PATH"] = empty
        self.assertIn("cloudflared isn't available", self.addon._start_from_preferences(self.preferences))
        self.assertIn(("label", "cloudflared isn't available"), self.draw())


if __name__ == "__main__":
    unittest.main(verbosity=2)
