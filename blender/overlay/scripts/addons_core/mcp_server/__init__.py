# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
MCP server: lets AI assistants (such as Claude, in Claude Code or the Claude apps) use Blender
through the Model Context Protocol.

Background mode (e.g. on a server)::

   blender --background --python-expr "import mcp_server; mcp_server.serve_forever(port=8765)"

Custom connectors of the Claude apps need a public HTTPS address: the server can start a Cloudflare
tunnel (``cloudflared``, bundled with Blender for Android), see :mod:`mcp_server.tunnel`.
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

import atexit
import os
import secrets
import socket
import sys
import time
import urllib.parse

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import protocol, tools, tunnel

_server: protocol.Server | None = None
_tunnel: tunnel.Tunnel | None = None
# The public address of a custom tunnel / reverse proxy (`https://host`).
_custom_public_url = ""
_executor = tools.MainThreadExecutor()
# Seconds between checks for requests on the main thread.
TIMER_INTERVAL = 0.05
# Set from the tunnel's thread, the interface is redrawn on the main thread.
_redraw_needed = False
# Time of the last request shown in the interface (redrawn for new requests).
_last_request_time = 0.0
# Requests shown in the interface.
RECENT_REQUESTS_SHOWN = 4

PUBLIC_ACCESS_ITEMS = (
    ('NONE', "Off",
     "No public address: only clients on this device (or on the local network)"),
    ('QUICK', "Quick Tunnel",
     "Public HTTPS address from Cloudflare (trycloudflare.com), no account needed. "
     "The address changes every time the server starts"),
    ('TOKEN', "Cloudflare Tunnel",
     "Fixed public HTTPS address: a tunnel of your Cloudflare account (free) with a public host name "
     "of your domain routed to http://localhost:<port>, connected with its token"),
    ('CUSTOM', "Custom URL",
     "Your own HTTPS tunnel or reverse proxy to this device (e.g. Tailscale Funnel, ngrok)"),
)


def _log(message: str) -> None:
    print(message)


def _tag_redraw() -> None:
    global _redraw_needed
    _redraw_needed = True


def _redraw() -> None:
    global _redraw_needed
    _redraw_needed = False
    window_manager = bpy.context.window_manager
    if window_manager is None:
        return
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type in {'VIEW_3D', 'PREFERENCES'}:
                area.tag_redraw()


def _timer() -> float | None:
    global _last_request_time
    if _server is None:
        return None
    _executor.process()
    requests = _server.recent_requests()
    if requests and requests[-1]["time"] != _last_request_time:
        _last_request_time = requests[-1]["time"]
        _tag_redraw()
    if _redraw_needed:
        _redraw()
    return TIMER_INTERVAL


def _android_call(name: str, enable: bool) -> None:
    """Call a function of the Android application (`creator_android.cc`)."""
    if sys.platform != "android" or bpy.app.background:
        return
    import ctypes
    try:
        # `ctypes.pythonapi` is `libblender.so` on Android.
        function = getattr(ctypes.pythonapi, name)
    except AttributeError:
        return
    function.argtypes = (ctypes.c_int,)
    function.restype = None
    function(int(enable))


def _android_keep_alive(enable: bool) -> None:
    """Keep running while another app is in the foreground (a foreground service on Android)."""
    _android_call("blender_android_keep_alive", enable)


# Whether the processor is kept awake for the public address (see `_keep_awake`).
_keep_awake_held = False


def _keep_awake(enable: bool) -> None:
    """
    Keep the processor running while the screen is off (a wake lock on Android), while the server
    has a public address: the device would sleep and the tunnel be disconnected.
    """
    global _keep_awake_held
    if enable != _keep_awake_held:
        _keep_awake_held = enable
        _android_call("blender_android_keep_awake", enable)


def _copy_secret(context: bpy.types.Context, text: str) -> None:
    """
    Copy a text with the token to the clipboard: on Android marked as sensitive (no preview,
    not kept in the keyboard's clipboard history).
    """
    if sys.platform == "android" and not bpy.app.background:
        import ctypes
        try:
            function = ctypes.pythonapi.blender_android_copy_sensitive
        except AttributeError:
            function = None
        if function is not None:
            function.argtypes = (ctypes.c_char_p,)
            function.restype = ctypes.c_int
            if function(text.encode("utf-8")):
                return
    context.window_manager.clipboard = text


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


def _tunnel_home() -> str:
    """cloudflared's files: a private directory of this user (not a configuration of another user)."""
    return bpy.utils.user_resource('CONFIG', path="mcp_cloudflared", create=True)


def start_tunnel(*, token: str = "", hostname: str = "") -> tunnel.Tunnel:
    """
    Start a Cloudflare tunnel to the running server: a quick tunnel without ``token``.

    :raises RuntimeError: cloudflared isn't available or the server isn't running.
    """
    global _tunnel
    stop_tunnel()
    if _server is None:
        raise RuntimeError("The MCP server isn't running")
    executable = tunnel.find_executable()
    if executable is None:
        raise RuntimeError("cloudflared isn't available (it's included in Blender for Android, "
                           "otherwise install it from Cloudflare)")
    instance = tunnel.Tunnel(
        executable=executable,
        local_url="http://127.0.0.1:{:d}".format(_server.port),
        token=token,
        hostname=hostname,
        home=_tunnel_home(),
        log=_log,
        on_change=_tag_redraw,
    )
    instance.start()
    _tunnel = instance
    return instance


def stop_tunnel() -> None:
    global _tunnel
    if _tunnel is None:
        return
    _tunnel.stop()
    _tunnel = None
    _tag_redraw()


def public_url() -> str:
    """Public address of the server (``https://host``), empty when there is none (yet)."""
    if _tunnel is not None:
        return _tunnel.public_url
    return _custom_public_url


def connector_url(token: str) -> str:
    """URL for custom connectors of the Claude apps (the token in the path), empty without address."""
    origin = public_url()
    return "{:s}/mcp/{:s}".format(origin, token) if origin else ""


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
    # Blender's own check of the public address isn't a request from the internet (panel).
    server.unlisted_header = (tunnel.CHECK_HEADER.lower(), tunnel.CHECK_NONCE)
    server.start()
    _server = server
    if not bpy.app.background:
        bpy.app.timers.register(_timer, first_interval=TIMER_INTERVAL, persistent=True)
    _android_keep_alive(True)
    _log("MCP server listening on {:s}:{:d}".format(server.host, server.port))
    return server


def stop() -> None:
    global _server, _custom_public_url
    stop_tunnel()
    _custom_public_url = ""
    _keep_awake(False)
    if _server is None:
        return
    _server.stop()
    _server = None
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    _android_keep_alive(False)
    _log("MCP server stopped")


def serve_forever(
        *,
        port: int = 8765,
        token: str | None = None,
        allow_network: bool = False,
        public: str = 'NONE',
        tunnel_token: str | None = None,
        tunnel_hostname: str = "",
) -> None:
    """
    Serve requests until interrupted, for background mode (``--background``) where there is no
    event loop to run requests on the main thread.

    :arg token: From the ``BLENDER_MCP_TOKEN`` environment variable when not given, a random
       token is generated & printed otherwise.
    :arg public: Public HTTPS address: ``'QUICK'`` (Cloudflare quick tunnel) or ``'TOKEN'``
       (Cloudflare tunnel, ``tunnel_token`` or the ``TUNNEL_TOKEN`` environment variable).
    """
    if public not in {'NONE', 'QUICK', 'TOKEN'}:
        raise ValueError("public must be 'NONE', 'QUICK' or 'TOKEN', not {!r}".format(public))
    tunnel_token = (tunnel_token or os.environ.get("TUNNEL_TOKEN", "")).strip() if public == 'TOKEN' else ""
    if public == 'TOKEN' and not tunnel_token:
        raise ValueError("public='TOKEN' needs tunnel_token (or the TUNNEL_TOKEN environment variable)")
    token = token or os.environ.get("BLENDER_MCP_TOKEN") or secrets.token_urlsafe(24)
    server = start(port=port, token=token, allow_network=allow_network)
    try:
        if not os.environ.get("BLENDER_MCP_TOKEN"):
            print("MCP token:", token)
        print("MCP end-point: http://{:s}:{:d}/mcp".format(server.host, server.port), flush=True)
        if public != 'NONE':
            instance = start_tunnel(token=tunnel_token, hostname=tunnel_hostname)
            if instance.wait_ready(timeout=180.0):
                print("MCP public end-point: {:s}/mcp (Claude connector: {:s}/mcp/<token>){:s}".format(
                    instance.public_url, instance.public_url,
                    "" if instance.reachable else ", the address doesn't answer yet"), flush=True)
            elif instance.state == tunnel.Tunnel.CONNECTED:
                print("MCP tunnel: connected, the public host name isn't known (tunnel_hostname)", flush=True)
            else:
                print("MCP tunnel: not connected:", instance.error or instance.state, flush=True)
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
    public_access: EnumProperty(
        name="Public Address",
        description=(
            "Public HTTPS address of the server, needed by custom connectors of the Claude apps "
            "(they connect from the internet)"
        ),
        items=PUBLIC_ACCESS_ITEMS,
        default='NONE',
    )
    tunnel_token: StringProperty(
        name="Tunnel Token",
        description=(
            "Token of your Cloudflare tunnel (Cloudflare dashboard: Networks > Tunnels > the tunnel > "
            "install connector, the long value after \"--token\")"
        ),
        subtype='PASSWORD',
        default="",
    )
    tunnel_hostname: StringProperty(
        name="Public Host Name",
        description=(
            "Public host name of the tunnel (e.g. blender.example.com), routed to "
            "http://localhost:<port> in the Cloudflare dashboard"
        ),
        default="",
    )
    keep_awake: BoolProperty(
        name="Keep Awake",
        description=(
            "Keep the processor running while the screen is off and the server has a public address: "
            "otherwise the device sleeps and Claude can't reach Blender (uses more battery)"
        ),
        default=True,
    )
    custom_public_url: StringProperty(
        name="Public URL",
        description="HTTPS address of your tunnel or reverse proxy to this server (e.g. https://phone.example.ts.net)",
        default="",
    )

    def draw(self, context: bpy.types.Context) -> None:
        _draw_settings(self.layout, self)


def _start_from_preferences(preferences: "MCP_AddonPreferences") -> str:
    """Start the server (and its public address) with the preferences, an error message on failure."""
    if not preferences.token:
        preferences.token = secrets.token_urlsafe(24)
    try:
        start(port=preferences.port, token=preferences.token, allow_network=preferences.allow_network)
    except OSError as ex:
        return "Unable to start the MCP server: {!s}".format(ex)
    return _start_public_access(preferences)


def custom_public_url(url: str) -> tuple[str, str]:
    """
    The base of connector URLs for a custom public URL (``https://host[/path]``, without the
    end-point) and an error message when it can't be used by the Claude apps.
    """
    url = url.strip().rstrip("/")
    if url.endswith("/mcp"):
        url = url[:-4]
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "", "Invalid public URL"
    if parts.scheme != "https":
        return "", "The public URL must start with https://"
    if not parts.hostname or "." not in parts.hostname:
        return "", "The public URL needs a host name (e.g. https://phone.example.ts.net)"
    if port not in {None, 443}:
        return "", "The Claude apps only connect to port 443 (no port in the URL)"
    if parts.query or parts.fragment:
        return "", "The public URL can't have a query (?...) or fragment (#...)"
    return "https://{:s}{:s}".format(parts.hostname, parts.path), ""


def _start_public_access(preferences: "MCP_AddonPreferences") -> str:
    error = _start_public_access_impl(preferences)
    _keep_awake(not error and preferences.public_access != 'NONE' and preferences.keep_awake)
    return error


def _start_public_access_impl(preferences: "MCP_AddonPreferences") -> str:
    global _custom_public_url
    stop_tunnel()
    _custom_public_url = ""
    if preferences.public_access == 'CUSTOM':
        url, error = custom_public_url(preferences.custom_public_url)
        if error:
            return error
        _custom_public_url = url
    elif preferences.public_access in {'QUICK', 'TOKEN'}:
        if preferences.public_access == 'TOKEN' and not preferences.tunnel_token.strip():
            return "Paste the token of your Cloudflare tunnel first"
        try:
            start_tunnel(
                token=preferences.tunnel_token.strip() if preferences.public_access == 'TOKEN' else "",
                hostname=preferences.tunnel_hostname if preferences.public_access == 'TOKEN' else "",
            )
        except (OSError, RuntimeError) as ex:
            return "Unable to start the tunnel: {!s}".format(ex)
    return ""


def _draw_public_access(layout: bpy.types.UILayout, preferences: "MCP_AddonPreferences", running: bool) -> None:
    box = layout.box()
    box.label(text="Claude App Connector (HTTPS)", icon='WORLD')
    sub = box.column()
    sub.enabled = not running
    sub.prop(preferences, "public_access", text="")
    if preferences.public_access == 'TOKEN':
        sub.prop(preferences, "tunnel_token")
        sub.prop(preferences, "tunnel_hostname")
    elif preferences.public_access == 'CUSTOM':
        sub.prop(preferences, "custom_public_url")
    if preferences.public_access == 'NONE':
        return
    if sys.platform == "android":
        sub.prop(preferences, "keep_awake")
    if preferences.public_access in {'QUICK', 'TOKEN'} and tunnel.find_executable() is None:
        box.label(text="cloudflared isn't available", icon='ERROR')
    if not running:
        if preferences.public_access == 'QUICK':
            box.label(text="A new address every start (update the connector)", icon='INFO')
        return

    ready = False
    if _tunnel is not None:
        state = _tunnel.state
        reachable = _tunnel.reachable
        if state == tunnel.Tunnel.CONNECTED and reachable:
            box.label(text="Ready", icon='CHECKMARK')
            ready = True
        elif state == tunnel.Tunnel.CONNECTED and reachable is None:
            box.label(text="Connected, checking the address...", icon='SORTTIME')
        elif state == tunnel.Tunnel.CONNECTED:
            box.label(text="Connected, the address doesn't answer yet", icon='ERROR')
            ready = True
        elif state == tunnel.Tunnel.STARTING:
            box.label(text="Connecting to Cloudflare...", icon='SORTTIME')
        elif _tunnel.retry_in > 0.0:
            box.label(text="Tunnel stopped, starting again soon", icon='ERROR')
        else:
            box.label(text="Tunnel stopped", icon='ERROR')
        if _tunnel.error and state != tunnel.Tunnel.CONNECTED:
            box.label(text=_tunnel.error[:120])
        if _tunnel.warning:
            box.label(text=_tunnel.warning[:120], icon='ERROR')
        if _tunnel.public_url:
            box.label(text=_tunnel.public_url.removeprefix("https://") + "/mcp/...")
        elif not _tunnel.is_quick and state == tunnel.Tunnel.CONNECTED:
            box.label(text="Set the public host name for the connector URL", icon='INFO')
        if _tunnel.address_changed and ready:
            box.label(text="New address: edit the connector's URL (or add it again)", icon='ERROR')
        box.operator("mcp.restart_tunnel", icon='FILE_REFRESH')
    elif preferences.public_access in {'QUICK', 'TOKEN'}:
        box.label(text="Tunnel not running", icon='ERROR')
        box.operator("mcp.restart_tunnel", icon='PLAY')
    elif _custom_public_url:
        box.label(text=_custom_public_url.removeprefix("https://") + "/mcp/...")
        ready = True
    row = box.row()
    row.enabled = ready and bool(connector_url(preferences.token))
    row.operator("mcp.copy_connector_url", icon='COPYDOWN')
    box.label(text="claude.ai: Customize > Connectors > Add custom connector")

    # What the connector does (e.g. whether Claude connected), requests from the internet.
    requests = [request for request in _server.recent_requests() if request["proxied"]] if _server else []
    if requests:
        col = box.column(align=True)
        col.label(text="Requests from the internet:")
        for request in requests[-RECENT_REQUESTS_SHOWN:]:
            col.label(text="{:s}  {:s}  {:d}{:s}".format(
                time.strftime("%H:%M:%S", time.localtime(request["time"])),
                request["rpc"] or request["method"], request["status"],
                "  " + request["error"][:60] if request.get("error") else ""))


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

    _draw_public_access(col, preferences, running)

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
        error = _start_from_preferences(_preferences())
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'} if _server is None else {'FINISHED'}
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
            # The tunnel (and its address) is kept.
            _server.token = preferences.token
        return {'FINISHED'}


class MCP_OT_copy_claude_code_command(bpy.types.Operator):
    """Copy the command adding this server to Claude Code"""
    bl_idname = "mcp.copy_claude_code_command"
    bl_label = "Copy Claude Code Command"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        url = _endpoint_urls(preferences)[0]
        _copy_secret(context, (
            "claude mcp add --transport http blender {:s} --header \"Authorization: Bearer {:s}\"".format(
                url, preferences.token)
        ))
        self.report({'INFO'}, "Copied to the clipboard")
        return {'FINISHED'}


class MCP_OT_copy_url_with_token(bpy.types.Operator):
    """Copy the server URL containing the token, for clients that can't send headers """ \
        """(e.g. a custom connector in the Claude apps, through a tunnel to this device)"""
    bl_idname = "mcp.copy_url_with_token"
    bl_label = "Copy URL with Token"

    def execute(self, context: bpy.types.Context) -> set[str]:
        preferences = _preferences()
        _copy_secret(context, "{:s}/{:s}".format(_endpoint_urls(preferences)[0], preferences.token))
        self.report({'INFO'}, "Copied to the clipboard")
        return {'FINISHED'}


class MCP_OT_copy_connector_url(bpy.types.Operator):
    """Copy the HTTPS URL for a custom connector of the Claude apps (claude.ai: Customize > """ \
        """Connectors > Add custom connector, no sign-in), it contains the token"""
    bl_idname = "mcp.copy_connector_url"
    bl_label = "Copy Connector URL"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _server is not None and bool(public_url())

    def execute(self, context: bpy.types.Context) -> set[str]:
        _copy_secret(context, connector_url(_preferences().token))
        if _tunnel is not None:
            _tunnel.acknowledge_address()
        self.report({'INFO'}, "Copied to the clipboard")
        return {'FINISHED'}


class MCP_OT_restart_tunnel(bpy.types.Operator):
    """Start the tunnel again (a quick tunnel gets a new address)"""
    bl_idname = "mcp.restart_tunnel"
    bl_label = "Restart Tunnel"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return _server is not None

    def execute(self, context: bpy.types.Context) -> set[str]:
        error = _start_public_access(_preferences())
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
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
    MCP_OT_copy_connector_url,
    MCP_OT_restart_tunnel,
    VIEW3D_PT_mcp_server,
)


def _auto_start() -> None:
    preferences = _preferences()
    if preferences.auto_start and preferences.token and _server is None:
        error = _start_from_preferences(preferences)
        if error:
            _log("MCP server: {:s}".format(error))
    return None


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background:
        bpy.app.timers.register(_auto_start, first_interval=1.0)
    # The tunnel is a separate process.
    atexit.register(stop_tunnel)


def unregister() -> None:
    stop()
    atexit.unregister(stop_tunnel)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
