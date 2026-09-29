# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
MCP server: lets AI assistants (such as Claude, in Claude Code or the Claude apps) use Blender
through the Model Context Protocol.

Background mode (e.g. on a server)::

   blender --background --python-expr "import mcp_server; mcp_server.serve_forever(port=8765)"
"""

bl_info = {
    "name": "MCP Server",
    "author": "Blender for Android contributors",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Sidebar > MCP",
    "description": "Let AI assistants (Claude Code, Claude apps) use Blender through the Model Context Protocol",
    "category": "System",
    "support": "COMMUNITY",
}

import os
import secrets
import socket
import sys

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import protocol, tools

_server: protocol.Server | None = None
_executor = tools.MainThreadExecutor()
# Seconds between checks for requests on the main thread.
TIMER_INTERVAL = 0.05


def _log(message: str) -> None:
    print(message)


def _timer() -> float | None:
    if _server is None:
        return None
    _executor.process()
    return TIMER_INTERVAL


def _android_keep_alive(enable: bool) -> None:
    """Keep running while another app is in the foreground (a foreground service on Android)."""
    if sys.platform != "android" or bpy.app.background:
        return
    import ctypes
    try:
        # `ctypes.pythonapi` is `libblender.so` on Android.
        function = ctypes.pythonapi.blender_android_keep_alive
    except AttributeError:
        return
    function.argtypes = (ctypes.c_int,)
    function.restype = None
    function(int(enable))


def local_addresses() -> list[str]:
    """IP addresses of this device on the local network (best effort)."""
    addresses = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            # No packet is sent, only selects the interface of the default route.
            sock.connect(("192.0.2.1", 9))
            addresses.append(sock.getsockname()[0])
        except OSError:
            pass
    return addresses


def start(*, port: int, token: str, allow_network: bool) -> protocol.Server:
    global _server
    stop()
    server = protocol.Server(
        host="0.0.0.0" if allow_network else "127.0.0.1",
        port=port,
        token=token,
        tools=tools.create_tools(),
        executor=_executor,
        server_info={"name": "blender", "title": "Blender", "version": bpy.app.version_string},
        instructions=tools.instructions(),
        log=_log,
    )
    server.start()
    _server = server
    if not bpy.app.background:
        bpy.app.timers.register(_timer, first_interval=TIMER_INTERVAL, persistent=True)
    _android_keep_alive(True)
    _log("MCP server listening on {:s}:{:d}".format(server.host, server.port))
    return server


def stop() -> None:
    global _server
    if _server is None:
        return
    _server.stop()
    _server = None
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    _android_keep_alive(False)
    _log("MCP server stopped")


def serve_forever(*, port: int = 8765, token: str | None = None, allow_network: bool = False) -> None:
    """
    Serve requests until interrupted, for background mode (``--background``) where there is no
    event loop to run requests on the main thread.

    :arg token: From the ``BLENDER_MCP_TOKEN`` environment variable when not given, a random
       token is generated & printed otherwise.
    """
    token = token or os.environ.get("BLENDER_MCP_TOKEN") or secrets.token_urlsafe(24)
    server = start(port=port, token=token, allow_network=allow_network)
    if not os.environ.get("BLENDER_MCP_TOKEN"):
        print("MCP token:", token)
    print("MCP end-point: http://{:s}:{:d}/mcp".format(server.host, server.port), flush=True)
    try:
        while _server is not None:
            _executor.process(timeout=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop()


# -----------------------------------------------------------------------------
# Preferences & Interface

def _preferences() -> "MCP_AddonPreferences":
    return bpy.context.preferences.addons[__package__].preferences


def _endpoint_urls(preferences: "MCP_AddonPreferences") -> list[str]:
    hosts = ["127.0.0.1"]
    if preferences.allow_network:
        hosts = local_addresses() + hosts
    return ["http://{:s}:{:d}/mcp".format(host, preferences.port) for host in hosts]


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: IntProperty(
        name="Port",
        description="TCP port of the MCP server",
        default=8765,
        min=1024,
        max=65535,
    )
    allow_network: BoolProperty(
        name="Allow Network Access",
        description=(
            "Accept connections from other devices on the network (otherwise only from this device, "
            "e.g. Claude Code running in a terminal app or through \"adb forward\")"
        ),
        default=False,
    )
    token: StringProperty(
        name="Token",
        description="Secret required from clients, anyone with it can run code in Blender",
        subtype='PASSWORD',
        default="",
    )
    auto_start: BoolProperty(
        name="Start Automatically",
        description="Start the server when Blender starts",
        default=False,
    )

    def draw(self, context: bpy.types.Context) -> None:
        _draw_settings(self.layout, self)


def _draw_settings(layout: bpy.types.UILayout, preferences: MCP_AddonPreferences) -> None:
    running = _server is not None
    col = layout.column()
    row = col.row(align=True)
    if running:
        row.operator("mcp.stop", icon='PAUSE')
    else:
        row.operator("mcp.start", icon='PLAY')
    col.label(text="Running" if running else "Stopped", icon='CHECKMARK' if running else 'X')

    sub = col.column()
    sub.enabled = not running
    sub.prop(preferences, "port")
    sub.prop(preferences, "allow_network")
    col.prop(preferences, "auto_start")

    if running:
        box = col.box()
        for url in _endpoint_urls(preferences):
            box.label(text=url)
        box.operator("mcp.copy_claude_code_command", icon='COPYDOWN')
        box.operator("mcp.copy_url_with_token", icon='COPYDOWN')
    col.operator("mcp.new_token", icon='FILE_REFRESH')
    col.label(text="Anyone with the token can run code in Blender.", icon='ERROR')


class MCP_OT_start(bpy.types.Operator):
    """Start the MCP server"""
    bl_idname = "mcp.start"
    bl_label = "Start MCP Server"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        if not preferences.token:
            preferences.token = secrets.token_urlsafe(24)
        try:
            start(port=preferences.port, token=preferences.token, allow_network=preferences.allow_network)
        except OSError as ex:
            self.report({'ERROR'}, "Unable to start the MCP server: {!s}".format(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class MCP_OT_stop(bpy.types.Operator):
    """Stop the MCP server"""
    bl_idname = "mcp.stop"
    bl_label = "Stop MCP Server"

    def execute(self, context: bpy.types.Context) -> set[str]:
        stop()
        return {'FINISHED'}


class MCP_OT_new_token(bpy.types.Operator):
    """Generate a new token, clients using the old token can't connect anymore"""
    bl_idname = "mcp.new_token"
    bl_label = "New Token"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        preferences.token = secrets.token_urlsafe(24)
        if _server is not None:
            start(port=preferences.port, token=preferences.token, allow_network=preferences.allow_network)
        return {'FINISHED'}


class MCP_OT_copy_claude_code_command(bpy.types.Operator):
    """Copy the command adding this server to Claude Code"""
    bl_idname = "mcp.copy_claude_code_command"
    bl_label = "Copy Claude Code Command"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        url = _endpoint_urls(preferences)[0]
        context.window_manager.clipboard = (
            "claude mcp add --transport http blender {:s} --header \"Authorization: Bearer {:s}\"".format(
                url, preferences.token)
        )
        self.report({'INFO'}, "Copied to the clipboard")
        return {'FINISHED'}


class MCP_OT_copy_url_with_token(bpy.types.Operator):
    """Copy the server URL containing the token, for clients that can't send headers """ \
        """(e.g. a custom connector in the Claude apps, through a tunnel to this device)"""
    bl_idname = "mcp.copy_url_with_token"
    bl_label = "Copy URL with Token"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        context.window_manager.clipboard = "{:s}/{:s}".format(_endpoint_urls(preferences)[0], preferences.token)
        self.report({'INFO'}, "Copied to the clipboard")
        return {'FINISHED'}


class VIEW3D_PT_mcp_server(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MCP"
    bl_label = "MCP Server"

    def draw(self, context: bpy.types.Context) -> None:
        _draw_settings(self.layout, _preferences())


classes = (
    MCP_AddonPreferences,
    MCP_OT_start,
    MCP_OT_stop,
    MCP_OT_new_token,
    MCP_OT_copy_claude_code_command,
    MCP_OT_copy_url_with_token,
    VIEW3D_PT_mcp_server,
)


def _auto_start() -> None:
    preferences = _preferences()
    if preferences.auto_start and preferences.token and _server is None:
        try:
            start(port=preferences.port, token=preferences.token, allow_network=preferences.allow_network)
        except OSError as ex:
            _log("MCP server: unable to start: {!s}".format(ex))
    return None


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background:
        bpy.app.timers.register(_auto_start, first_interval=1.0)


def unregister() -> None:
    stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
