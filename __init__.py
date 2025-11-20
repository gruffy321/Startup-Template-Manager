bl_info = {
    "name": "Startup Preset Manager",
    "author": "Gruff Wright",
    "version": (2, 5, 0),
    "blender": (4, 3, 0),
    "description": "Saves, loads, and manages addon dependencies for custom startup file presets.",
    "category": "Presets"
}

from .preset_startup_manager_rc import register, unregister

if __name__ == "__main__":
    register()
