# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Tools exposed to MCP clients, running on Blender's main thread.
"""

__all__ = (
    "MainThreadExecutor",
    "create_tools",
    "instructions",
)

import base64
import contextlib
import io
import json
import os
import queue
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

import bpy
import mathutils

from .protocol import Tool, ToolError

# Maximum length of text returned by a tool (characters).
MAX_TEXT_LENGTH = 100_000

INSTRUCTIONS = """\
This server controls a running Blender {version} ({platform}) through its Python API.

- Use `execute_python` to run Python code with the `bpy` module (the full Blender Python API),
  e.g. to create and edit objects, materials, modifiers, geometry nodes, animations and scenes.
  Changes are visible live in Blender's interface and can be undone there.
- Prefer the data API (`bpy.data`, object & mesh properties) over operators (`bpy.ops`):
  operators depend on the context (active editor, mode, selection).
- Check results visually with `get_viewport_screenshot` (the 3D viewport) or `render_image`.
- `get_scene_info` & `get_object_info` describe the scene without writing code.
- NumPy is available (`import numpy`).
"""

# Optional components of the Android port (`android_components` add-on).
INSTRUCTIONS_ANDROID = """- On Android, optional components are installed after the application with the
  `android_components` module (enabled by default): `android_components.available()` lists
  them, `android_components.install("usd-python")` installs USD's Python API
  (`from pxr import Usd`), `android_components.pip_install(["package"])` installs Python
  packages (pure Python or Android wheels). Downloads need online access
  (`bpy.app.online_access`, Preferences > System > Network).
"""


class _Job:
    __slots__ = ("function", "done", "result", "error", "cancelled")

    def __init__(self, function: Callable[[], Any]) -> None:
        self.function = function
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self.cancelled = False


class MainThreadExecutor:
    """Runs functions from other threads on Blender's main thread (``bpy`` isn't thread safe)."""

    def __init__(self) -> None:
        self._queue: queue.Queue[_Job] = queue.Queue()

    def __call__(self, function: Callable[[], Any], timeout: float) -> Any:
        job = _Job(function)
        self._queue.put(job)
        if not job.done.wait(timeout):
            job.cancelled = True
            raise TimeoutError()
        if job.error is not None:
            raise job.error
        return job.result

    def process(self, timeout: float = 0.0) -> None:
        """Run queued jobs, call on the main thread. Waits up to ``timeout`` for a job."""
        while True:
            try:
                job = self._queue.get(timeout=timeout) if timeout > 0.0 else self._queue.get_nowait()
            except queue.Empty:
                return
            timeout = 0.0
            if job.cancelled:
                continue
            try:
                job.result = job.function()
            except BaseException as ex:
                job.error = ex
            job.done.set()


# -----------------------------------------------------------------------------
# Helpers

def _text(text: str) -> dict[str, Any]:
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n... (truncated, {:d} characters in total)".format(len(text))
    return {"type": "text", "text": text}


def _json(value: Any) -> dict[str, Any]:
    return _text(json.dumps(value, indent=1, default=str))


def _round(values: Any, digits: int = 4) -> list[float]:
    return [round(float(v), digits) for v in values]


def _image_content(filepath: str, max_size: int) -> dict[str, Any]:
    """PNG image content block, scaled down to ``max_size`` pixels (largest side)."""
    image = bpy.data.images.load(filepath, check_existing=False)
    try:
        width, height = image.size
        if max_size > 0 and max(width, height) > max_size:
            scale = max_size / max(width, height)
            image.scale(max(1, round(width * scale)), max(1, round(height * scale)))
            image.filepath_raw = filepath
            image.file_format = 'PNG'
            image.save()
    finally:
        bpy.data.images.remove(image)
    with open(filepath, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    return {"type": "image", "data": data, "mimeType": "image/png"}


def _temp_png() -> str:
    fd, filepath = tempfile.mkstemp(prefix="blender_mcp_", suffix=".png")
    os.close(fd)
    return filepath


def _ui_refresh(undo_message: str | None) -> None:
    """Redraw the interface & add an undo step after changes."""
    if bpy.app.background:
        return
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    if undo_message:
        with contextlib.suppress(Exception):
            window = wm.windows[0]
            with bpy.context.temp_override(window=window):
                bpy.ops.ed.undo_push(message=undo_message)


def _object_summary(obj: bpy.types.Object) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "name": obj.name,
        "type": obj.type,
        "location": _round(obj.location),
        "rotation_euler": _round(obj.rotation_euler),
        "scale": _round(obj.scale),
        "dimensions": _round(obj.dimensions),
        "visible": obj.visible_get(),
    }
    if obj.parent:
        summary["parent"] = obj.parent.name
    if obj.data is not None:
        summary["data"] = obj.data.name
    materials = [slot.material.name for slot in obj.material_slots if slot.material]
    if materials:
        summary["materials"] = materials
    if obj.modifiers:
        summary["modifiers"] = [modifier.type for modifier in obj.modifiers]
    return summary


# -----------------------------------------------------------------------------
# Tools

# Persistent name-space of `execute_python` (like an interactive console).
_python_namespace: dict[str, Any] = {}


def _execute_python(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    code = arguments["code"]
    if arguments.get("reset_namespace") or not _python_namespace:
        _python_namespace.clear()
        _python_namespace.update({"__name__": "__mcp__", "bpy": bpy, "mathutils": mathutils})
        with contextlib.suppress(ImportError):
            import numpy
            _python_namespace["np"] = numpy
    _python_namespace.pop("result", None)

    output = io.StringIO()
    error = None
    try:
        compiled = compile(code, "<mcp>", "exec")
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exec(compiled, _python_namespace)
    except BaseException as ex:
        if isinstance(ex, SystemExit):
            error = "SystemExit is not allowed"
        else:
            # Skip this function's frame.
            error = "".join(traceback.format_exception(type(ex), ex, ex.__traceback__.tb_next))
    finally:
        _ui_refresh("MCP: Python")

    text = output.getvalue()
    if "result" in _python_namespace:
        text += ("\n" if text and not text.endswith("\n") else "") + "result = " + repr(_python_namespace["result"])
    if error is not None:
        raise ToolError((text + "\n" if text else "") + error)
    return [_text(text or "(no output)")]


def _get_scene_info(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    limit = int(arguments.get("max_objects", 200))
    scene = bpy.context.scene
    objects = list(scene.objects)
    info = {
        "blender_version": bpy.app.version_string,
        "file": bpy.data.filepath or None,
        "is_dirty": bpy.data.is_dirty,
        "scene": scene.name,
        "scenes": [s.name for s in bpy.data.scenes],
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "frame_current": scene.frame_current,
        "frame_range": [scene.frame_start, scene.frame_end],
        "camera": scene.camera.name if scene.camera else None,
        "active_object": bpy.context.view_layer.objects.active.name
        if bpy.context.view_layer.objects.active else None,
        "selected_objects": [obj.name for obj in bpy.context.view_layer.objects if obj.select_get()],
        "object_count": len(objects),
        "objects": [_object_summary(obj) for obj in objects[:limit]],
        "counts": {
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "node_groups": len(bpy.data.node_groups),
            "images": len(bpy.data.images),
            "collections": len(bpy.data.collections),
        },
    }
    return [_json(info)]


def _get_object_info(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    obj = bpy.data.objects.get(arguments["name"])
    if obj is None:
        raise ToolError("No object named {!r}".format(arguments["name"]))
    info = _object_summary(obj)
    info["matrix_world"] = [_round(row) for row in obj.matrix_world]
    info["bound_box_world"] = [_round(obj.matrix_world @ mathutils.Vector(corner)) for corner in obj.bound_box]
    info["collections"] = [collection.name for collection in obj.users_collection]
    if obj.modifiers:
        info["modifiers"] = [{"name": m.name, "type": m.type, "show_viewport": m.show_viewport}
                             for m in obj.modifiers]
    if obj.type == 'MESH':
        mesh = obj.data
        info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "uv_layers": [layer.name for layer in mesh.uv_layers],
            "attributes": [attribute.name for attribute in mesh.attributes],
        }
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh_eval = evaluated.to_mesh()
        info["mesh_evaluated"] = {
            "vertices": len(mesh_eval.vertices),
            "faces": len(mesh_eval.polygons),
        }
        evaluated.to_mesh_clear()
    elif obj.type == 'CAMERA':
        info["camera"] = {"lens": obj.data.lens, "type": obj.data.type}
    elif obj.type == 'LIGHT':
        info["light"] = {"type": obj.data.type, "energy": obj.data.energy, "color": _round(obj.data.color)}
    custom = {key: obj[key] for key in obj.keys() if not key.startswith("_")}
    if custom:
        info["custom_properties"] = custom
    return [_json(info)]


def _find_view3d() -> tuple[Any, Any, Any] | None:
    best = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            if region is None:
                continue
            if best is None or area.width * area.height > best[1].width * best[1].height:
                best = (window, area, region)
    return best


def _get_viewport_screenshot(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    if bpy.app.background:
        raise ToolError("No interface in background mode, use render_image instead")
    found = _find_view3d()
    if found is None:
        raise ToolError("No 3D viewport is open")
    window, area, region = found
    filepath = _temp_png()
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=filepath, check_existing=False)
        return [_image_content(filepath, int(arguments.get("max_size", 1024)))]
    finally:
        with contextlib.suppress(OSError):
            os.remove(filepath)


def _render_image(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    scene = bpy.context.scene
    if scene.camera is None:
        raise ToolError("The scene has no camera (set `scene.camera`)")
    render = scene.render
    settings = {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "filepath": render.filepath,
    }
    image_settings = (render.image_settings.file_format, render.image_settings.color_mode)
    cycles_samples = scene.cycles.samples if hasattr(scene, "cycles") else None
    filepath = _temp_png()
    try:
        if arguments.get("engine"):
            render.engine = arguments["engine"]
        if arguments.get("width"):
            render.resolution_x = int(arguments["width"])
        if arguments.get("height"):
            render.resolution_y = int(arguments["height"])
        render.resolution_percentage = 100
        if arguments.get("samples") and render.engine == 'CYCLES':
            scene.cycles.samples = int(arguments["samples"])
        render.image_settings.file_format = 'PNG'
        render.image_settings.color_mode = 'RGBA'
        render.filepath = filepath
        start = time.monotonic()
        bpy.ops.render.render(write_still=True)
        elapsed = time.monotonic() - start
        return [
            _text("Rendered {:d}x{:d} with {:s} in {:.1f}s".format(
                render.resolution_x, render.resolution_y, render.engine, elapsed)),
            _image_content(filepath, int(arguments.get("max_size", 1024))),
        ]
    finally:
        for key, value in settings.items():
            setattr(render, key, value)
        render.image_settings.file_format, render.image_settings.color_mode = image_settings
        if cycles_samples is not None:
            scene.cycles.samples = cycles_samples
        with contextlib.suppress(OSError):
            os.remove(filepath)


def _save_blend_file(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    filepath = arguments.get("filepath") or bpy.data.filepath
    if not filepath:
        raise ToolError("The file was never saved, give a file path")
    filepath = bpy.path.abspath(filepath)
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=filepath)
    return [_text("Saved: " + filepath)]


def create_tools() -> list[Tool]:
    read_only = {"readOnlyHint": True, "openWorldHint": False}
    return [
        Tool(
            "execute_python",
            (
                "Run Python code in Blender (on its main thread) with access to the full API: "
                "`bpy`, `mathutils` and `np` (NumPy) are pre-imported. Returns what the code "
                "prints; assign a value to `result` to return its representation. Variables "
                "persist between calls. Errors return the traceback."
            ),
            {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute."},
                    "reset_namespace": {
                        "type": "boolean",
                        "description": "Clear variables defined by earlier calls first.",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
            _execute_python,
            annotations={"destructiveHint": True, "openWorldHint": False},
        ),
        Tool(
            "get_scene_info",
            "Describe the current scene: file, render settings, camera, selection and objects "
            "(type, transform, materials, modifiers).",
            {
                "type": "object",
                "properties": {
                    "max_objects": {"type": "integer", "description": "Maximum number of objects listed (200)."},
                },
                "additionalProperties": False,
            },
            _get_scene_info,
            annotations=read_only,
        ),
        Tool(
            "get_object_info",
            "Details of one object: transform, bounding box, collections, modifiers, mesh statistics "
            "(original & evaluated), camera/light settings and custom properties.",
            {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Object name."}},
                "required": ["name"],
                "additionalProperties": False,
            },
            _get_object_info,
            annotations=read_only,
        ),
        Tool(
            "get_viewport_screenshot",
            "Screenshot of the (largest) 3D viewport as it's shown in Blender's interface.",
            {
                "type": "object",
                "properties": {
                    "max_size": {"type": "integer", "description": "Maximum width/height in pixels (1024)."},
                },
                "additionalProperties": False,
            },
            _get_viewport_screenshot,
            annotations=read_only,
        ),
        Tool(
            "render_image",
            (
                "Render the scene from its active camera and return the image. Settings given here "
                "only apply to this render. Rendering can take a while on a phone: prefer small "
                "sizes and few samples for previews."
            ),
            {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "description": "Width in pixels (scene setting)."},
                    "height": {"type": "integer", "description": "Height in pixels (scene setting)."},
                    "samples": {"type": "integer", "description": "Cycles samples (scene setting)."},
                    "engine": {
                        "type": "string",
                        "enum": ["CYCLES", "BLENDER_EEVEE", "BLENDER_WORKBENCH"],
                        "description": "Render engine (scene setting).",
                    },
                    "max_size": {
                        "type": "integer",
                        "description": "Maximum width/height of the returned image (1024).",
                    },
                },
                "additionalProperties": False,
            },
            _render_image,
            annotations={"readOnlyHint": True, "openWorldHint": False},
        ),
        Tool(
            "save_blend_file",
            "Save the .blend file (to its current path, or to the given path).",
            {
                "type": "object",
                "properties": {"filepath": {"type": "string", "description": "Path to save to."}},
                "additionalProperties": False,
            },
            _save_blend_file,
            annotations={"destructiveHint": False, "openWorldHint": False},
        ),
    ]


def instructions() -> str:
    text = INSTRUCTIONS.format(version=bpy.app.version_string, platform=sys.platform)
    if sys.platform == "android":
        text += INSTRUCTIONS_ANDROID
    return text
