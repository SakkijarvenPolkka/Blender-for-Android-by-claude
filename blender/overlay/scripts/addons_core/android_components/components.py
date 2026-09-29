# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Download, verification and installation of optional components (no ``bpy.types`` here, the
functions run in background threads).

A component is a ZIP archive made by the build of the application (``scripts/build_components.sh``)::

    component.json          {"id", "name", "version", "abi"}
    site-packages/...       Python modules, extracted into a directory on ``sys.path``

Components contain native code built against this build of Blender (``abi``): they are only
installed when the ``abi`` matches ``datafiles/android/build_info.json``. The list of components
of a release (``components.json``) is downloaded from the release of the application's version.
"""

import hashlib
import json
import os
import shutil
import site
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

import bpy

# Paths are looked up once, on the main thread.
_ROOT = bpy.utils.user_resource('DATAFILES', path="android_components", create=True)
SITE_PACKAGES = os.path.join(_ROOT, "site-packages")
_RECORDS = os.path.join(_ROOT, "installed")
_CATALOG = os.path.join(_ROOT, "catalog.json")
# (`system_resource` only finds directories.)
_BUILD_INFO_PATH = os.path.join(bpy.utils.system_resource('DATAFILES', path="android"), "build_info.json")

USER_AGENT = "Blender-for-Android/{:s}".format(bpy.app.version_string)
TIMEOUT = 60.0


class Component:
    def __init__(self, data, base_url):
        self.id = data["id"]
        self.name = data.get("name", self.id)
        self.description = data.get("description", "")
        self.version = data.get("version", "")
        self.file = data["file"]
        self.size = int(data.get("size", 0))
        self.sha256 = data.get("sha256", "")
        self.base_url = base_url

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "size": self.size,
            "url": self.base_url + self.file,
        }


def format_size(size):
    if size >= 1024 * 1024:
        return "{:.1f} MB".format(size / (1024 * 1024))
    return "{:.0f} KB".format(size / 1024)


def build_info():
    """Information about this build (written by ``scripts/build_blender.sh``)."""
    try:
        with open(_BUILD_INFO_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, TypeError, ValueError):
        return {}


def add_python_paths():
    """Make the installed Python modules importable."""
    os.makedirs(SITE_PACKAGES, exist_ok=True)
    if SITE_PACKAGES not in sys.path:
        # After Blender's own modules & bundled packages, processing `.pth` files.
        site.addsitedir(SITE_PACKAGES)


# -----------------------------------------------------------------------------
# Downloads

def _check_online_access():
    if not bpy.app.online_access:
        raise RuntimeError("Online access is disabled (Preferences > System > Network > Allow Online Access)")


def _open_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def _download(url, path, expected_sha256=""):
    digest = hashlib.sha256()
    with _open_url(url) as response, open(path, "wb") as fh:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            fh.write(chunk)
    if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
        raise RuntimeError("Checksum mismatch for {:s}".format(url))


def _release_urls(info):
    """Base URLs where the components of this build may be published."""
    repository = info.get("repository", "")
    if not repository:
        return []
    urls = []
    if tag := info.get("release_tag"):
        urls.append("https://github.com/{:s}/releases/download/{:s}/".format(repository, tag))
    urls.append("https://github.com/{:s}/releases/latest/download/".format(repository))
    return urls


def catalog(refresh=False):
    """Components available for this build (downloads the list when ``refresh`` is set)."""
    data = None
    if not refresh:
        try:
            with open(_CATALOG, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
    else:
        _check_online_access()
        info = build_info()
        errors = []
        for base_url in _release_urls(info):
            try:
                with _open_url(base_url + "components.json") as response:
                    manifest = json.load(response)
            except Exception as ex:
                errors.append("{:s}: {:s}".format(base_url, str(ex)))
                continue
            if manifest.get("abi") == info.get("abi"):
                data = {"base_url": base_url, "components": manifest.get("components", [])}
                break
            errors.append("{:s}: made for another build".format(base_url))
        if data is None:
            data = {"base_url": "", "components": [], "errors": errors}
        os.makedirs(_ROOT, exist_ok=True)
        with open(_CATALOG, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        if not data["components"]:
            raise RuntimeError(
                "No components published for this build, install them from a file\n" + "\n".join(errors))
    return [Component(item, data["base_url"]) for item in data.get("components", [])]


# -----------------------------------------------------------------------------
# Installation

def installed():
    versions = {}
    if os.path.isdir(_RECORDS):
        for filename in os.listdir(_RECORDS):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(_RECORDS, filename), encoding="utf-8") as fh:
                        versions[filename[:-5]] = json.load(fh).get("version", "")
                except (OSError, ValueError):
                    pass
    return versions


def install(component_id):
    components = {component.id: component for component in catalog(refresh=False)}
    if component_id not in components:
        components = {component.id: component for component in catalog(refresh=True)}
    component = components.get(component_id)
    if component is None:
        raise RuntimeError("Unknown component: {:s}".format(component_id))
    _check_online_access()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, component.file)
        _download(component.base_url + component.file, path, component.sha256)
        return install_file(path)


def _safe_path(root, name):
    path = os.path.realpath(os.path.join(root, name))
    if os.path.commonpath([path, os.path.realpath(root)]) != os.path.realpath(root):
        raise RuntimeError("Invalid path in archive: {:s}".format(name))
    return path


def install_file(filepath):
    """Install a component archive, returns a message."""
    info = build_info()
    with zipfile.ZipFile(filepath) as archive:
        try:
            meta = json.loads(archive.read("component.json"))
        except KeyError:
            raise RuntimeError("Not a component archive (no component.json)")
        component_id = meta["id"]
        if info.get("abi") and meta.get("abi") != info.get("abi"):
            raise RuntimeError(
                "{:s} was made for another build of Blender for Android ({:s}, this build: {:s})".format(
                    component_id, meta.get("abi", "?"), info["abi"]))

        remove(component_id)
        os.makedirs(SITE_PACKAGES, exist_ok=True)
        top_level = set()
        for member in archive.infolist():
            if not member.filename.startswith("site-packages/") or member.filename == "site-packages/":
                continue
            relative = member.filename[len("site-packages/"):]
            top_level.add(relative.split("/", 1)[0])
            target = _safe_path(SITE_PACKAGES, relative)
            if member.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)

    os.makedirs(_RECORDS, exist_ok=True)
    with open(os.path.join(_RECORDS, component_id + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"version": meta.get("version", ""), "name": meta.get("name", component_id),
                   "paths": sorted(top_level)}, fh, indent=2)
    add_python_paths()
    return "Installed {:s} {:s}".format(meta.get("name", component_id), meta.get("version", ""))


def remove(component_id):
    record_path = os.path.join(_RECORDS, component_id + ".json")
    try:
        with open(record_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return
    for name in record.get("paths", []):
        path = _safe_path(SITE_PACKAGES, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    os.remove(record_path)


# -----------------------------------------------------------------------------
# Python packages (pip)

def _run_pip(args):
    _check_online_access()
    command = ["-m", "pip", *args, "--disable-pip-version-check", "--no-input"]
    executable = sys.executable
    if executable and os.access(executable, os.X_OK) and os.path.basename(executable) != "blender":
        # Python's executable (Blender runs itself otherwise).
        process = subprocess.run(
            [executable, *command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output = process.stdout
        if process.returncode != 0:
            raise RuntimeError(output.strip().splitlines()[-1] if output.strip() else "pip failed")
        return output
    # No Python executable: run pip in this process.
    from pip._internal.cli.main import main as pip_main
    if pip_main(command[2:]) != 0:
        raise RuntimeError("pip failed, see the console output")
    return ""


def pip_install(packages, upgrade=False):
    args = ["install", "--target", SITE_PACKAGES, "--prefer-binary"]
    if upgrade:
        args.append("--upgrade")
    output = _run_pip(args + list(packages))
    add_python_paths()
    lines = [line for line in output.splitlines() if line.startswith("Successfully")]
    return lines[-1] if lines else "Installed: " + " ".join(packages)


def pip_list():
    """Packages installed with ``pip_install`` (name, version)."""
    import importlib.metadata
    if not os.path.isdir(SITE_PACKAGES):
        return []
    packages = []
    for dist in importlib.metadata.distributions(path=[SITE_PACKAGES]):
        packages.append((dist.metadata["Name"] or "?", dist.version or ""))
    return sorted(packages, key=lambda item: item[0].lower())


def pip_uninstall(packages):
    """Remove packages installed in the components' directory (``pip uninstall`` can't)."""
    import importlib.metadata
    names = {name.lower().replace("_", "-") for name in packages}
    removed = []
    for dist in importlib.metadata.distributions(path=[SITE_PACKAGES]):
        name = (dist.metadata["Name"] or "").lower().replace("_", "-")
        if name not in names:
            continue
        for file in dist.files or ():
            path = _safe_path(SITE_PACKAGES, str(file))
            if os.path.isfile(path):
                os.remove(path)
        # The metadata directory & empty package directories.
        shutil.rmtree(str(dist._path), ignore_errors=True)
        removed.append(dist.metadata["Name"])
    for entry in os.listdir(SITE_PACKAGES):
        path = os.path.join(SITE_PACKAGES, entry)
        if os.path.isdir(path) and not any(files for _, _, files in os.walk(path)):
            shutil.rmtree(path, ignore_errors=True)
    return "Removed: " + (", ".join(removed) if removed else "nothing")
