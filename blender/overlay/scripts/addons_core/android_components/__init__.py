# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Optional components of Blender for Android, installed after the application:

- Components built together with the application (e.g. USD's Python modules, ``pxr``),
  downloaded from the release of the application's version or installed from a file.
- Python packages from the Python Package Index (``pip``): pure Python packages and
  packages with binaries for Android (``android_*_arm64_v8a`` wheels).

Everything is installed in Blender's user resources (kept with application updates), Python
modules in a directory added to ``sys.path``.

The functions of this module can also be used from Python (e.g. by an AI assistant through the
MCP server)::

    import android_components
    android_components.available()                # Components of this build.
    android_components.install("usd-python")      # Download & install (blocking).
    android_components.pip_install(["networkx"])  # Python packages.
"""

bl_info = {
    "name": "Android Components",
    "author": "Blender for Android contributors",
    "version": (1, 0, 0),
    "blender": (5, 2, 0),
    "location": "Preferences > Add-ons > Android Components, Edit > Android Components",
    "description": "Install optional components (USD Python modules, Python packages) after the application",
    "category": "System",
    "support": "COMMUNITY",
}

import threading

import bpy
from bpy.props import StringProperty

from . import components

# Status of the last or running task, shown in the preferences.
_task_lock = threading.Lock()
_task = {"running": False, "title": "", "message": ""}


# -----------------------------------------------------------------------------
# Functions (also usable from Python scripts)

def available(refresh=False):
    """The components of this build: a list of dictionaries, see ``components.Component``."""
    return [component.as_dict() for component in components.catalog(refresh=refresh)]


def installed():
    """The installed components and their versions (``{id: version}``)."""
    return components.installed()


def install(component_id):
    """Download and install a component of this build (blocking)."""
    return components.install(component_id)


def install_file(filepath):
    """Install a component from a downloaded archive (blocking)."""
    return components.install_file(filepath)


def remove(component_id):
    """Remove an installed component."""
    components.remove(component_id)


def pip_install(packages, upgrade=False):
    """Install Python packages with ``pip`` (blocking), returns pip's output."""
    return components.pip_install(packages, upgrade=upgrade)


def pip_uninstall(packages):
    """Uninstall Python packages installed with ``pip_install``."""
    return components.pip_uninstall(packages)


# -----------------------------------------------------------------------------
# Background tasks (downloads can take a while, keep the interface responsive)

def _redraw_preferences():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PREFERENCES':
                area.tag_redraw()


def _run_task(title, function, *args):
    with _task_lock:
        if _task["running"]:
            return False
        _task.update(running=True, title=title, message="")

    def run():
        try:
            result = function(*args)
            message = result if isinstance(result, str) else "Done"
        except Exception as ex:
            message = "Error: {:s}".format(str(ex))
        with _task_lock:
            _task.update(running=False, message=message)

    def poll():
        _redraw_preferences()
        with _task_lock:
            if _task["running"]:
                return 0.5
        print("Android Components: {:s}: {:s}".format(title, _task["message"]))
        return None

    threading.Thread(target=run, name="AndroidComponents", daemon=True).start()
    bpy.app.timers.register(poll, first_interval=0.5)
    return True


class ANDROID_OT_component_install(bpy.types.Operator):
    """Download and install a component"""
    bl_idname = "android.component_install"
    bl_label = "Install Component"

    component_id: StringProperty()

    def execute(self, context):
        if not _run_task("Install {:s}".format(self.component_id), components.install, self.component_id):
            self.report({'WARNING'}, "Another task is running")
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDROID_OT_component_install_file(bpy.types.Operator):
    """Install a component from a downloaded archive (.zip)"""
    bl_idname = "android.component_install_file"
    bl_label = "Install Component from File"

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.zip", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if not _run_task("Install from file", components.install_file, self.filepath):
            self.report({'WARNING'}, "Another task is running")
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDROID_OT_component_remove(bpy.types.Operator):
    """Remove an installed component"""
    bl_idname = "android.component_remove"
    bl_label = "Remove Component"

    component_id: StringProperty()

    def execute(self, context):
        components.remove(self.component_id)
        return {'FINISHED'}


def _check_for_components():
    count = len(components.catalog(refresh=True))
    return "{:d} component(s) available for this build".format(count)


class ANDROID_OT_components_refresh(bpy.types.Operator):
    """Check which components are available for this build"""
    bl_idname = "android.components_refresh"
    bl_label = "Check for Components"

    def execute(self, context):
        if not _run_task("Check for components", _check_for_components):
            self.report({'WARNING'}, "Another task is running")
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDROID_OT_pip_install(bpy.types.Operator):
    """Install Python packages from the Python Package Index (pip)"""
    bl_idname = "android.pip_install"
    bl_label = "Install Python Packages"

    packages: StringProperty(name="Packages", description="Package names separated by spaces")

    def execute(self, context):
        names = self.packages.split()
        if not names:
            return {'CANCELLED'}
        if not _run_task("pip install " + " ".join(names), components.pip_install, names):
            self.report({'WARNING'}, "Another task is running")
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDROID_OT_pip_uninstall(bpy.types.Operator):
    """Uninstall a Python package installed with pip"""
    bl_idname = "android.pip_uninstall"
    bl_label = "Uninstall Python Package"

    package: StringProperty()

    def execute(self, context):
        if not _run_task("pip uninstall " + self.package, components.pip_uninstall, [self.package]):
            self.report({'WARNING'}, "Another task is running")
            return {'CANCELLED'}
        return {'FINISHED'}


class ANDROID_OT_components_show(bpy.types.Operator):
    """Show the optional components in the preferences"""
    bl_idname = "android.components_show"
    bl_label = "Android Components"

    def execute(self, context):
        return bpy.ops.preferences.addon_show(module=__package__)


class AndroidComponentsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    pip_packages: StringProperty(
        name="Packages",
        description="Python packages to install, separated by spaces (e.g. \"networkx sympy\")",
    )

    def draw(self, context):
        layout = self.layout

        with _task_lock:
            task = dict(_task)
        if task["running"]:
            layout.label(text="{:s}...".format(task["title"]), icon='SORTTIME')
        elif task["message"]:
            box = layout.box()
            for line in task["message"].splitlines()[-6:]:
                box.label(text=line)

        info = components.build_info()
        installed_versions = components.installed()

        box = layout.box()
        row = box.row()
        row.label(text="Components", icon='PACKAGE')
        row.operator("android.components_refresh", text="", icon='FILE_REFRESH')
        catalog = components.catalog(refresh=False)
        if catalog:
            for component in catalog:
                col = box.column(align=True)
                row = col.row()
                row.label(text=component.name)
                version = installed_versions.get(component.id)
                if version:
                    row.label(text="Installed", icon='CHECKMARK')
                    row.operator("android.component_remove", text="Remove").component_id = component.id
                else:
                    row.label(text=components.format_size(component.size))
                    op = row.operator("android.component_install", text="Install", icon='IMPORT')
                    op.component_id = component.id
                    row.enabled = not task["running"]
                col.label(text=component.description)
        else:
            box.label(text="No component list yet (check for components, needs Internet access)")
        for component_id in sorted(installed_versions):
            if not any(component.id == component_id for component in catalog):
                row = box.row()
                row.label(text="{:s} (installed)".format(component_id), icon='CHECKMARK')
                row.operator("android.component_remove", text="Remove").component_id = component_id
        box.operator("android.component_install_file", icon='FILE_FOLDER')
        box.label(text="Build: {:s}".format(info.get("abi", "unknown")))

        box = layout.box()
        box.label(text="Python Packages (pip)", icon='SCRIPT')
        row = box.row(align=True)
        row.prop(self, "pip_packages", text="")
        op = row.operator("android.pip_install", text="Install", icon='IMPORT')
        op.packages = self.pip_packages
        row.enabled = not task["running"]
        box.label(text="Pure Python packages and packages with Android wheels (arm64-v8a).")
        for name, version in components.pip_list():
            row = box.row()
            row.label(text="{:s} {:s}".format(name, version))
            row.operator("android.pip_uninstall", text="", icon='X').package = name

        if not bpy.context.preferences.system.use_online_access:
            layout.label(text="Downloads need online access: Preferences > System > Network", icon='ERROR')


def _menu_edit(self, context):
    self.layout.separator()
    self.layout.operator("android.components_show", icon='PACKAGE')


classes = (
    ANDROID_OT_component_install,
    ANDROID_OT_component_install_file,
    ANDROID_OT_component_remove,
    ANDROID_OT_components_refresh,
    ANDROID_OT_pip_install,
    ANDROID_OT_pip_uninstall,
    ANDROID_OT_components_show,
    AndroidComponentsPreferences,
)


def register():
    components.add_python_paths()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_edit.append(_menu_edit)


def unregister():
    bpy.types.TOPBAR_MT_edit.remove(_menu_edit)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
