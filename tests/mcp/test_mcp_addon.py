# SPDX-License-Identifier: GPL-2.0-or-later
"""
Tests of the MCP server add-on's public address handling (Claude app connectors) without Blender:
``bpy`` is replaced by a minimal stand-in, cloudflared by a program printing its messages.

  python3 tests/mcp/test_mcp_addon.py
"""

import importlib
import os
import stat
import sys
import tempfile
import time
import types
import unittest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADDONS_DIR = os.path.join(REPO_DIR, "blender", "overlay", "scripts", "addons_core")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_mcp_host import FAKE_CLOUDFLARED  # noqa: E402


def _install_fake_bpy():
    """Just what the add-on uses at import time & in its interface code."""
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(
        AddonPreferences=object, Operator=object, Panel=object,
        Context=object, UILayout=object, Object=object,
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
    bpy.utils = types.SimpleNamespace(register_class=lambda cls: None, unregister_class=lambda cls: None)
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
        with open(executable, "w") as fh:
            fh.write(FAKE_CLOUDFLARED.format(python=sys.executable))
        os.chmod(executable, os.stat(executable).st_mode | stat.S_IEXEC)
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
        self.assertTrue(self.addon._tunnel.wait_connected(timeout=20.0))
        # Forwards to the server's port.
        self.assertEqual(self.addon._tunnel.local_url, "http://127.0.0.1:{:d}".format(self.addon._server.port))
        self.assertEqual(self.addon.connector_url("addon-token"),
                         "https://seasonal-deck-organisms-sf.trycloudflare.com/mcp/addon-token")
        record = self.draw()
        self.assertIn(("label", "Connected"), record)
        self.assertIn(("operator", "mcp.copy_connector_url"), record)
        self.assertIn(("label", "seasonal-deck-organisms-sf.trycloudflare.com/mcp/..."), record)
        # The token isn't shown.
        self.assertFalse(any("addon-token" in str(item) for item in record))
        # The interface is redrawn from the main thread (timer).
        self.assertTrue(self.addon._redraw_needed)
        self.addon._timer()
        self.assertFalse(self.addon._redraw_needed)

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
        self.assertTrue(self.addon._tunnel.wait_connected(timeout=20.0))
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

    def test_failing_tunnel(self):
        self.preferences.public_access = 'QUICK'
        os.environ["FAKE_MODE"] = "fail"
        self.assertEqual(self.addon._start_from_preferences(self.preferences), "")
        self.assertFalse(self.addon._tunnel.wait_connected(timeout=20.0))
        record = self.draw()
        self.assertIn(("label", "Tunnel stopped"), record)
        self.assertTrue(any("failed to request quick Tunnel" in str(item) for item in record), record)
        self.assertEqual(self.addon.connector_url("t"), "")

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
