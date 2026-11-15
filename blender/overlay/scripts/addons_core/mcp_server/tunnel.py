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

The address only works some seconds after cloudflared reports it (DNS), it's checked before it's
reported as ready: a connector added too early fails (and the failure is cached for a while).

This module doesn't depend on ``bpy``.
"""

__all__ = (
    "Tunnel",
    "check_public_url",
    "find_executable",
    "normalize_hostname",
    "redact",
)

import collections
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

# Printed by cloudflared (in a table) when the quick tunnel was created: words with hyphens, not
# other addresses of the service such as `https://api.trycloudflare.com` in error messages.
QUICK_TUNNEL_URL_RE = re.compile(
    r"(?:^|[\s|])(https://[a-z0-9]+(?:-[a-z0-9]+)+\.trycloudflare\.com)(?=[\s|]|$)")
# A connection to Cloudflare's network is up (cloudflared keeps several).
CONNECTED_RE = re.compile(r"\bRegistered tunnel connection\b")
# Level of a log line: `2026-11-15T08:00:00Z ERR message key=value`.
LEVEL_RE = re.compile(r"^\S+\s+(DBG|INF|WRN|ERR|FTL)\s+(.*)$")
# Configuration of a named tunnel (from the dashboard): `config="{\"ingress\":[...]}"`.
CONFIG_RE = re.compile(r'\bconfig=("(?:[^"\\]|\\.)*")')
# Quick tunnels are rate limited.
RATE_LIMITED_RE = re.compile(r"\bstatus 429\b|Too Many Requests", re.IGNORECASE)
# Exit code of cloudflared for usage errors (e.g. an invalid tunnel token): not started again.
USAGE_ERROR_CODE = 255

# Secrets that may appear in cloudflared's messages (e.g. the URL of a failed request).
_REDACT = (
    (re.compile(r"(/mcp/)[^\s\"'\\/?#]+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[^\s\"'\\]+"), r"\1***"),
    (re.compile(r"(?i)(token[=:]\s*)[^\s\"'\\]{16,}"), r"\1***"),
)

LOG_LINES = 200
# Seconds before starting cloudflared again after it exited (the last value is repeated).
RETRY_DELAYS = (10.0, 20.0, 40.0, 80.0, 160.0, 300.0)
# Quick tunnels: Cloudflare limits how often they can be created.
RATE_LIMIT_DELAY = 60.0
# Seconds to wait for the public address to work.
CHECK_TIMEOUT = 90.0


def find_executable() -> str | None:
    """The cloudflared executable: bundled with the Android application, otherwise on the path."""
    for variable in ("BLENDER_CLOUDFLARED", "BLENDER_ANDROID_CLOUDFLARED"):
        path = os.environ.get(variable)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("cloudflared")


def normalize_hostname(hostname: str) -> str:
    """The host name of a URL or host name (``https://Host.example.com/mcp`` -> ``host.example.com``)."""
    hostname = hostname.strip()
    if not hostname:
        return ""
    try:
        return urllib.parse.urlsplit(hostname if "://" in hostname else "//" + hostname).hostname or ""
    except ValueError:
        return ""


def redact(text: str) -> str:
    """Remove the MCP token (and other credentials) from a message."""
    for pattern, replacement in _REDACT:
        text = pattern.sub(replacement, text)
    return text


def _dns_resolves(host: str, timeout: float) -> bool | None:
    """
    Whether the host has an address, asking Cloudflare's DNS directly (DNS over HTTPS): asking the
    system's resolver before the record exists would cache the failure. None when DoH fails.
    """
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": host, "type": "A"})
    request = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return answer.get("Status") == 0 and bool(answer.get("Answer"))


def _server_answers(url: str, timeout: float) -> bool:
    """Whether the MCP server answers at the public address (unauthorized: no token is sent)."""
    request = urllib.request.Request(url + "/mcp", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, body = response.status, response.read(4096)
    except urllib.error.HTTPError as ex:
        status, body = ex.code, ex.read(4096)
    except OSError:
        return False
    # Not an error page of Cloudflare (e.g. 530 while the tunnel isn't registered).
    return status == 401 and b"Unauthorized" in body


def check_public_url(url: str, *, timeout: float = CHECK_TIMEOUT,
                     stop: threading.Event | None = None) -> bool:
    """Wait until the public address reaches this server (DNS published, tunnel connected)."""
    stop = stop or threading.Event()
    end = time.monotonic() + timeout
    host = urllib.parse.urlsplit(url).hostname or ""
    use_dns = True
    while time.monotonic() < end and not stop.is_set():
        if use_dns:
            resolves = _dns_resolves(host, timeout=10.0)
            # DNS over HTTPS may be blocked, then the system's resolver is used.
            use_dns = resolves is not None
            if resolves is False:
                stop.wait(2.0)
                continue
        if _server_answers(url, timeout=15.0):
            return True
        stop.wait(3.0)
    return False


class Tunnel:
    """
    Runs cloudflared, forwarding requests from its public address to ``local_url``. cloudflared is
    started again when it exits (e.g. without network when starting).

    :arg token: Tunnel token of a Cloudflare account (named tunnel), a quick tunnel when empty.
    :arg hostname: Public host name of the named tunnel, otherwise the one routed to
       ``local_url`` in the tunnel's configuration (from the dashboard) is used.
    :arg home: Directory for cloudflared's files (``HOME``): a configuration file in
       ``~/.cloudflared`` would prevent quick tunnels.
    :arg on_change: Called (from another thread) when the state or the address changes.
    :arg check: Waits until the public address works: ``(url, stop_event) -> bool``.
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
            check: Callable[[str, threading.Event], bool] | None = None,
            retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> None:
        self.executable = executable
        self.local_url = local_url
        self._token = token.strip()
        self._hostname = normalize_hostname(hostname)
        self._home = home
        self._log = log
        self._on_change = on_change
        self._check = check if check is not None else (lambda url, stop: check_public_url(url, stop=stop))
        self._retry_delays = retry_delays
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._state = Tunnel.STOPPED
        self._public_url = ""
        # None while the address is checked, then whether it works.
        self._reachable: bool | None = None
        self._error = ""
        self._warning = ""
        self._retry_at = 0.0
        self._retries = 0
        # The address of a quick tunnel changed after cloudflared was started again.
        self._address_changed = False
        self._lines: collections.deque[str] = collections.deque(maxlen=LOG_LINES)

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
    def reachable(self) -> bool | None:
        """Whether the public address works, None until checked."""
        with self._lock:
            return self._reachable

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def warning(self) -> str:
        """A problem of the tunnel's configuration (named tunnels)."""
        with self._lock:
            return self._warning

    @property
    def retry_in(self) -> float:
        """Seconds until cloudflared is started again (after it exited), zero otherwise."""
        with self._lock:
            return max(0.0, self._retry_at - time.monotonic()) if self._retry_at else 0.0

    @property
    def address_changed(self) -> bool:
        """The address of the quick tunnel changed, connectors must be updated."""
        with self._lock:
            return self._address_changed

    def acknowledge_address(self) -> None:
        """The new address was copied (to update the connector)."""
        self._set(address_changed=False)

    def log_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def _set(self, **values) -> None:
        changed = False
        with self._lock:
            for key, value in values.items():
                if getattr(self, "_" + key) != value:
                    setattr(self, "_" + key, value)
                    changed = True
        if changed and self._on_change is not None:
            self._on_change()

    # -------------------------------------------------------------------------
    # Life-time

    @property
    def _config_path(self) -> str:
        return os.path.join(self._home, "config.yml")

    @property
    def _pid_path(self) -> str:
        return os.path.join(self._home, "cloudflared.pid")

    def command(self) -> list[str]:
        """Arguments of cloudflared (the token is passed in the environment)."""
        args = [
            self.executable, "tunnel",
            # Only this (empty) configuration, never one of another cloudflared of the system
            # (`~/.cloudflared`, `/etc/cloudflared`): its ingress rules would replace `--url`.
            "--config", self._config_path,
            "--no-autoupdate",
            # Quick requests when stopping (the default waits 30 seconds for open requests).
            "--grace-period", "2s",
            # Never `debug`: it logs requests, with the token in the URL.
            "--loglevel", "info",
            # QUIC (UDP), falling back to HTTP/2 (TCP) on networks blocking UDP: without the
            # option, quick tunnels only use QUIC.
            "--protocol", "auto",
            "--edge-ip-version", "auto",
        ]
        if self.is_quick:
            args += ["--url", self.local_url]
        else:
            # The service of the public host name is configured in the dashboard.
            args += ["run"]
        return args

    def _prepare_home(self) -> None:
        """A private directory for cloudflared (a configuration of another user would be used)."""
        os.makedirs(self._home, mode=0o700, exist_ok=True)
        info = os.lstat(self._home)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or (
                hasattr(os, "getuid") and info.st_uid != os.getuid()):
            raise OSError("Unsafe directory for cloudflared: {:s}".format(self._home))
        os.chmod(self._home, 0o700)
        with open(self._config_path, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        self._stop_previous()

    def _stop_previous(self) -> None:
        """Stop the cloudflared of this directory still running after Blender ended (e.g. crashed)."""
        try:
            with open(self._pid_path, encoding="utf-8") as fh:
                pid = int(fh.read().strip())
            with open("/proc/{:d}/cmdline".format(pid), "rb") as fh:
                arguments = fh.read().split(b"\0")
        except (OSError, ValueError):
            return
        if self._config_path.encode("utf-8") in arguments:
            self._log("MCP tunnel: stopping the previous cloudflared (process {:d})".format(pid))
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def start(self) -> None:
        """Start cloudflared, :raises OSError: when it can't be run."""
        self.stop()
        try:
            self._prepare_home()
        except OSError as ex:
            self._set(state=Tunnel.FAILED, error=str(ex))
            raise
        self._stop_event = threading.Event()
        with self._lock:
            self._lines.clear()
            self._retries = 0
        self._set(address_changed=False, warning="", public_url="")
        try:
            self._spawn()
        except OSError as ex:
            self._set(state=Tunnel.FAILED, error="Unable to run cloudflared: {!s}".format(ex))
            raise

    def stop(self) -> None:
        self._stop_event.set()
        stopped = False
        # Until no thread is left: one may be starting cloudflared again.
        for _ in range(10):
            with self._lock:
                process, threads = self._process, self._threads
                self._process, self._threads = None, []
            if process is None and not threads:
                break
            if process is not None:
                stopped = True
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5.0)
            for thread in threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=5.0)
        if stopped:
            self._log("MCP tunnel: stopped")
            try:
                os.remove(self._pid_path)
            except OSError:
                pass
        self._set(state=Tunnel.STOPPED, retry_at=0.0)

    def wait_ready(self, timeout: float) -> bool:
        """
        Wait until the tunnel is connected and its address checked (see :attr:`reachable`),
        False when it isn't connected in time.
        """
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if self._state == Tunnel.CONNECTED and self._reachable is not None:
                    return True
                if self._state == Tunnel.STOPPED:
                    return False
            time.sleep(0.1)
        return self.state == Tunnel.CONNECTED

    def _spawn(self) -> None:
        if self._stop_event.is_set():
            return
        env = dict(os.environ)
        env["HOME"] = self._home
        # cloudflared reads the token from `TUNNEL_TOKEN` (not visible in the process arguments).
        env.pop("TUNNEL_TOKEN", None)
        if self._token:
            env["TUNNEL_TOKEN"] = self._token
        previous_url = self.public_url
        self._set(
            state=Tunnel.STARTING,
            public_url="" if self.is_quick else ("https://" + self._hostname if self._hostname else ""),
            reachable=None,
            error="",
            retry_at=0.0,
        )
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
        try:
            with open(self._pid_path, "w", encoding="utf-8") as fh:
                fh.write(str(process.pid))
        except OSError:
            pass
        thread = threading.Thread(target=self._read, args=(process, previous_url), name="MCPTunnel", daemon=True)
        with self._lock:
            self._process = process
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()
        self._log("MCP tunnel: cloudflared started ({:s} tunnel)".format("quick" if self.is_quick else "named"))

    def _restart_later(self, rate_limited: bool) -> None:
        with self._lock:
            delay = self._retry_delays[min(self._retries, len(self._retry_delays) - 1)]
            self._retries += 1
        if rate_limited:
            delay = max(delay, RATE_LIMIT_DELAY)
        self._set(retry_at=time.monotonic() + delay)
        self._log("MCP tunnel: starting cloudflared again in {:.0f} seconds".format(delay))
        if self._stop_event.wait(delay):
            return
        try:
            self._spawn()
        except OSError as ex:
            self._set(state=Tunnel.FAILED, error="Unable to run cloudflared: {!s}".format(ex), retry_at=0.0)

    def _check_address(self, url: str) -> None:
        reachable = self._check(url, self._stop_event)
        if self._stop_event.is_set() or self.public_url != url:
            return
        self._set(reachable=bool(reachable))
        self._log("MCP tunnel: the public address {:s}".format("works" if reachable else "doesn't answer (yet)"))

    # -------------------------------------------------------------------------
    # Output of cloudflared

    def _read(self, process: subprocess.Popen, previous_url: str) -> None:
        connected = False
        ready = False
        rate_limited = False
        # Lines without level: fatal errors are printed this way when cloudflared exits.
        plain: collections.deque[str] = collections.deque(maxlen=3)
        assert process.stdout is not None
        with process.stdout:
            for line in process.stdout:
                line = redact(line.rstrip())
                if not line:
                    continue
                with self._lock:
                    self._lines.append(line)
                if LEVEL_RE.match(line):
                    plain.clear()
                else:
                    plain.append(line.strip())
                rate_limited = rate_limited or bool(RATE_LIMITED_RE.search(line))
                connected = self._handle_line(line, connected)
                if not ready and connected and self.public_url:
                    ready = True
                    self._ready(self.public_url, previous_url)
        code = process.wait()
        if self._stop_event.is_set():
            return
        error = " ".join(plain) or self.error or "cloudflared exited (code {:d})".format(code)
        self._log("MCP tunnel: {:s}".format(error))
        self._set(state=Tunnel.FAILED, error=error, reachable=None)
        # Usage errors (e.g. an invalid tunnel token) don't go away.
        if code not in {USAGE_ERROR_CODE, -1}:
            self._restart_later(rate_limited)

    def _ready(self, url: str, previous_url: str) -> None:
        """Connected with a known address: check it works."""
        with self._lock:
            self._retries = 0
        if self.is_quick and previous_url and url != previous_url:
            self._set(address_changed=True)
        thread = threading.Thread(target=self._check_address, args=(url,), name="MCPTunnelCheck", daemon=True)
        with self._lock:
            self._threads.append(thread)
        thread.start()

    def _handle_line(self, line: str, connected: bool) -> bool:
        level = LEVEL_RE.match(line)
        if self.is_quick and not self.public_url and level and level.group(1) == "INF":
            match = QUICK_TUNNEL_URL_RE.search(level.group(2))
            if match:
                self._set(public_url=match.group(1))
                self._log("MCP tunnel: public address {:s}".format(match.group(1)))
        if not self.is_quick:
            self._handle_configuration(line)
        if CONNECTED_RE.search(line):
            if not connected:
                self._log("MCP tunnel: connected to Cloudflare")
            connected = True
            self._set(error="")
        if level and level.group(1) in {"ERR", "FTL"}:
            self._set(error=level.group(2).strip())
        if connected and self.public_url:
            self._set(state=Tunnel.CONNECTED)
        return connected

    def _handle_configuration(self, line: str) -> None:
        """The public host names of a named tunnel, from its configuration."""
        match = CONFIG_RE.search(line)
        if not match:
            return
        try:
            config = json.loads(json.loads(match.group(1)))
        except ValueError:
            return
        if not isinstance(config, dict):
            return
        rules = [rule for rule in config.get("ingress", ()) if isinstance(rule, dict) and rule.get("hostname")]
        if not rules:
            self._set(warning="The tunnel has no public host name (add one in the Cloudflare dashboard)")
            return
        port = urllib.parse.urlsplit(self.local_url).port
        routed = [rule for rule in rules if _service_port(str(rule.get("service", ""))) == port]
        if routed:
            self._set(warning="")
        else:
            self._set(warning="The public host name routes to {:s}, not to {:s}".format(
                str(rules[0].get("service", "?")), self.local_url.replace("127.0.0.1", "localhost")))
        if not self._hostname:
            hostname = str((routed or rules)[0]["hostname"])
            if self.public_url != "https://" + hostname:
                self._set(public_url="https://" + hostname)
                self._log("MCP tunnel: public address https://{:s}".format(hostname))


def _service_port(service: str) -> int | None:
    """The port of a local service (``http://localhost:8765``), None for other services."""
    parts = urllib.parse.urlsplit(service)
    if parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    try:
        return parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None
