

# Blender for Android: USD's plug-ins (file formats, asset resolver, schemas) are in Blender's
# data files, register them before the modules are used (Blender itself registers them when it
# first uses USD, the modules may be used before).
def _register_blender_plugins():
    try:
        import bpy
    except ImportError:
        return
    path = bpy.utils.system_resource('DATAFILES', path="usd")
    if path:
        from . import Plug
        Plug.Registry().RegisterPlugins(path)


_register_blender_plugins()
del _register_blender_plugins
