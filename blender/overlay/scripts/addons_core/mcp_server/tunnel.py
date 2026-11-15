# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Public HTTPS address for the MCP server with Cloudflare Tunnel (``cloudflared``).

Custom connectors of the Claude apps (web, mobile, desktop) call MCP servers from the internet and
only over HTTPS: the tunnel client connects out to Cloudflare, which forwards the requests to the
server on this device (no port forwarding, no certificate, also behind mobile networks).

- Quick tunnel: no account, a random ``https://<words>.trycloudflare.com`` address, a new one every
  time the tunnel starts.
- Tunnel token: a tunnel of a Cloudflare account, with a fixed address (a public host name of the
  account's domain, routed to ``http://localhost:<port>`` in Cloudflare's dashboard).

This module doesn't depend on ``bpy``.
"""

__all__ = (
    "Tunnel",
    "find_executable",
)

import collections
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

# Printed by cloudflared (in a table) when the quick tunnel was created: words with hyphens, not
# other addresses of the service such as `https://api.trycloudflare.com` in error messages.
QUICK_TUNNEL_URL_RE = re.compile(
    r"(?:^|[\s|])(https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com)(?=[\s|]|$)")
# A connection to Cloudflare's network is up (cloudflared keeps several).
CONNECTED_RE = re.compile(r"\bRegistered tunnel connection\b")
# Level of a log line: `2026-11-15T08:00:00Z ERR message key=value`.
LEVEL_RE = re.compile(r"^\S+\s+(DBG|INF|WRN|ERR|FTL)\s+(.*)$")

LOG_LINES = 200


def find_executable() -> str | None:
    """The cloudflared executable: bundled with the Android application, otherwise on the path."""
    for variable in ("BLENDER_CLOUDFLARED", "BLENDER_ANDROID_CLOUDFLARED"):
        path = os.environ.get(variable)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("cloudflared")


class Tunnel:
    """
    Runs cloudflared, forwarding requests from its public address to ``local_url``.

    :arg token: Tunnel token of a Cloudflare account (named tunnel), a quick tunnel when empty.
    :arg hostname: Public host name of the named tunnel (configured in Cloudflare's dashboard,
       cloudflared doesn't report it).
    :arg home: Directory for cloudflared's files (``HOME``): a configuration file in
       ``~/.cloudflared`` would prevent quick tunnels.
    :arg on_change: Called (from another thread) when the state or the address changes.
    """

    STARTING = 'STARTING'
    CONNECTED = 'CONNECTED'
    FAILED = 'FAILED'
    STOPPED = 'STOPPED'

    def __init__(
            self,
            *,
            executable: str,
            local_url: str,
            token: str = "",
            hostname: str = "",
            home: str,
            log: Callable[[str], None] = print,
            on_change: Callable[[], None] | None = None,
    ) -> None:
        self.executable = executable
        self.local_url = local_url
        self._token = token
        self._hostname = hostname.strip()
        self._home = home
        self._log = log
        self._on_change = on_change
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._state = Tunnel.STOPPED
        self._public_url = ""
        self._error = ""
        self._lines: collections.deque[str] = collections.deque(maxlen=LOG_LINES)
        self._stopping = False

    # -------------------------------------------------------------------------
    # State

    @property
    def is_quick(self) -> bool:
        return not self._token

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def public_url(self) -> str:
        """Public address (``https://host``), empty until known."""
        with self._lock:
            return self._public_url

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    def log_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def _set(self, *, state: str | None = None, public_url: str | None = None, error: str | None = None) -> None:
        changed = False
        with self._lock:
            if state is not None and state != self._state:
                self._state = state
                changed = True
            if public_url is not None and public_url != self._public_url:
                self._public_url = public_url
                changed = True
            if error is not None and error != self._error:
                self._error = error
                changed = True
        if changed and self._on_change is not None:
            self._on_change()

    # -------------------------------------------------------------------------
    # Life-time

    def command(self) -> list[str]:
        """Arguments of cloudflared (the token is passed in the environment)."""
        args = [
            self.executable, "tunnel",
            "--no-autoupdate",
            # Quick requests when stopping (the default waits 30 seconds for open requests).
            "--grace-period", "2s",
            "--loglevel", "info",
            # QUIC (UDP), falling back to HTTP/2 (TCP) on networks blocking UDP: without the
            # option, quick tunnels only use QUIC.
            "--protocol", "auto",
        ]
        if self.is_quick:
            args += ["--url", self.local_url]
        else:
            # The service of the public host name is configured in the dashboard.
            args += ["run"]
        return args

    def start(self) -> None:
        self.stop()
        os.makedirs(self._home, exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = self._home
        # cloudflared reads the token from `TUNNEL_TOKEN` (not visible in the process arguments).
        env.pop("TUNNEL_TOKEN", None)
        if self._token:
            env["TUNNEL_TOKEN"] = self._token
        with self._lock:
            self._lines.clear()
        self._stopping = False
        self._set(
            state=Tunnel.STARTING,
            public_url="" if self.is_quick else ("https://" + self._hostname if self._hostname else ""),
            error="",
        )
        try:
            process = subprocess.Popen(
                self.command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=self._home,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as ex:
            self._set(state=Tunnel.FAILED, error="Unable to run cloudflared: {!s}".format(ex))
            raise
        self._process = process
        self._thread = threading.Thread(target=self._read, args=(process,), name="MCPTunnel", daemon=True)
        self._thread.start()
        self._log("MCP tunnel: cloudflared started ({:s} tunnel)".format("quick" if self.is_quick else "named"))

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        self._stopping = True
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._process = None
        self._set(state=Tunnel.STOPPED)
        self._log("MCP tunnel: stopped")

    def wait_connected(self, timeout: float) -> bool:
        """Wait until the tunnel is connected (and its address known), False on failure or timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            state = self.state
            if state == Tunnel.CONNECTED:
                return True
            if state in {Tunnel.FAILED, Tunnel.STOPPED}:
                return False
            time.sleep(0.1)
        return False

    # -------------------------------------------------------------------------
    # Output of cloudflared

    def _read(self, process: subprocess.Popen) -> None:
        connected = False
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                line = line.rstrip()
                if not line:
                    continue
                with self._lock:
                    self._lines.append(line)
                connected = self._handle_line(line, connected)
        code = process.wait()
        if self._stopping:
            return
        error = self.error or "cloudflared exited (code {:d})".format(code)
        self._log("MCP tunnel: {:s}".format(error))
        self._set(state=Tunnel.FAILED, error=error)

    def _handle_line(self, line: str, connected: bool) -> bool:
        level = LEVEL_RE.match(line)
        if self.is_quick and not self.public_url and level and level.group(1) == "INF":
            match = QUICK_TUNNEL_URL_RE.search(level.group(2))
            if match:
                self._set(public_url=match.group(1))
                self._log("MCP tunnel: public address {:s}".format(match.group(1)))
        if CONNECTED_RE.search(line):
            if not connected:
                self._log("MCP tunnel: connected to Cloudflare")
            connected = True
            self._set(error="")
        if level and level.group(1) in {"ERR", "FTL"}:
            self._set(error=level.group(2).strip())
        if connected and (self.public_url or not self.is_quick):
            self._set(state=Tunnel.CONNECTED)
        return connected
