bl_info = {
    "name": "Startup Preset Manager",
    "author": "Gruff Wright 2025",
    "version": (2, 5),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > Startup Presets",
    "description": "Saves, loads, and manages addon dependencies for custom startup file presets.",
    "category": "Presets"
}

import bpy
import os
import json
from bpy.props import StringProperty, IntProperty, CollectionProperty, EnumProperty
from bpy.types import PropertyGroup, Operator, Panel, UIList, AddonPreferences
from bpy.utils import user_resource
from bpy.app.handlers import persistent

DEPENDENCY_TEXT_BLOCK = "PRESET_ADDON_DEPENDENCIES"

def get_default_presets_path():
    path = user_resource('SCRIPTS', path="startup_presets")
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def get_preset_manager_data(context):
    return context.preferences.addons[__package__].preferences

def get_runtime_presets_dir(context):
    prefs = get_preset_manager_data(context)
    preset_path = prefs.custom_dir
    if not os.path.exists(preset_path):
        os.makedirs(preset_path)
    return preset_path

def save_current_dependencies(context):
    """Save addon dependencies as a text block in the current blend file"""
    # Get list of currently enabled addons
    addon_list = list(bpy.context.preferences.addons.keys())
    
    # Create or update text block
    if DEPENDENCY_TEXT_BLOCK in bpy.data.texts:
        text = bpy.data.texts[DEPENDENCY_TEXT_BLOCK]
        text.clear()
    else:
        text = bpy.data.texts.new(DEPENDENCY_TEXT_BLOCK)
    
    # Store as JSON
    text.write(json.dumps(addon_list))
    print(f"Saved {len(addon_list)} addon dependencies to text block")

def load_dependencies_from_file(context):
    """Load addon dependencies from text block and populate window_manager"""
    if DEPENDENCY_TEXT_BLOCK not in bpy.data.texts:
        print("No dependency text block found in this file")
        return False
    
    try:
        text = bpy.data.texts[DEPENDENCY_TEXT_BLOCK]
        addon_list = json.loads(text.as_string())
        
        # Populate window_manager.preset_dependencies
        context.window_manager.preset_dependencies.clear()
        for addon_name in addon_list:
            item = context.window_manager.preset_dependencies.add()
            item.addon_name = addon_name
        
        print(f"Loaded {len(addon_list)} addon dependencies from text block")
        return True
    except Exception as e:
        print(f"Error loading dependencies: {e}")
        return False

class PREDATA_PG_Dependency(PropertyGroup):
    addon_name: StringProperty(name="Addon Name")

class PREDATA_PG_StartupPreset(PropertyGroup):
    name: StringProperty(default="New Preset")
    filepath: StringProperty(subtype='FILE_PATH')

class PRESET_ManagerAddonPreferences(AddonPreferences):
    bl_idname = __package__
    presets: CollectionProperty(type=PREDATA_PG_StartupPreset)
    preset_index: IntProperty(default=0)
    custom_dir: StringProperty(
        name="Preset Folder",
        description="The directory to save and load presets from.",
        subtype='DIR_PATH',
        default=get_default_presets_path()
    )
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Preset Storage Location (must be a valid path):")
        layout.prop(self, "custom_dir")

class PRESET_OT_SavePreset(Operator):
    bl_idname = "preset.save_current_preset"
    bl_label = "Save Current as New Preset"
    
    preset_name: StringProperty(name="Preset Name", default="My Custom Setup")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        prefs = get_preset_manager_data(context)
        presets_dir = get_runtime_presets_dir(context)
        
        filename = self.preset_name.strip()
        if not filename.lower().endswith(".blend"):
            filename += ".blend"
        filepath = os.path.join(presets_dir, filename)
        
        # Save dependencies to text block BEFORE saving the file
        save_current_dependencies(context)
        
        # Save the blend file
        bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=True)
        
        # Add to preset list
        item = prefs.presets.add()
        item.name = self.preset_name.strip()
        item.filepath = filepath
        
        self.report({'INFO'}, f"Preset saved: {item.name}")
        return {'FINISHED'}

class PRESET_OT_LoadPreset(Operator):
    bl_idname = "preset.load_selected_preset"
    bl_label = "Load Preset"
    
    @classmethod
    def poll(cls, context):
        prefs = get_preset_manager_data(context)
        return prefs.presets and prefs.preset_index >= 0
    
    def execute(self, context):
        prefs = get_preset_manager_data(context)
        index = prefs.preset_index
        
        if index < 0 or index >= len(prefs.presets):
            self.report({'ERROR'}, "No valid preset selected.")
            return {'CANCELLED'}
        
        preset = prefs.presets[index]
        bpy.ops.wm.read_homefile(filepath=preset.filepath)
        
        self.report({'INFO'}, f"Preset loaded: {preset.name}")
        return {'FINISHED'}

class PRESET_OT_ScanFolder(bpy.types.Operator):
    bl_idname = "preset.scan_folder"
    bl_label = "Re-Scan Preset Folder"
    
    def execute(self, context):
        try:
            scan_for_presets(context)
            self.report({'INFO'}, "Preset Folder scanned successfully.")
        except Exception as e:
            self.report({'ERROR'}, f"Scan Failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class PRESET_OT_DependencyQueue(bpy.types.Operator):
    bl_idname = "preset.dependency_queue"
    bl_label = "Queue Dependency Check"
    
    _timer = None
    
    def modal(self, context, event):
        if event.type == 'TIMER':
            context.window_manager.event_timer_remove(self._timer)
            # Invoke the actual dependency check operator
            if context.window_manager.preset_dependencies:
                bpy.ops.preset.check_dependencies('INVOKE_DEFAULT')
            return {'FINISHED'}
        return {'PASS_THROUGH'}
    
    def execute(self, context):
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

class PRESET_OT_DependencyCheck(bpy.types.Operator):
    bl_idname = "preset.check_dependencies"
    bl_label = "Adjust Dependencies"
    
    to_enable: CollectionProperty(type=PREDATA_PG_Dependency)
    to_disable: CollectionProperty(type=PREDATA_PG_Dependency)
    action: EnumProperty(
        items=[
            ('APPLY', "Apply Changes (Enable/Disable)", "Enable required and disable unneeded add-ons."),
            ('KEEP', "Keep Current Settings", "Do nothing to the currently enabled add-ons."),
        ],
        name="Action",
        default='APPLY',
    )
    
    def invoke(self, context, event):
        required = {d.addon_name for d in context.window_manager.preset_dependencies}
        current_enabled = {m for m in bpy.context.preferences.addons.keys()}
        
        # Get all installed addons using addon_utils
        import addon_utils
        all_installed = {mod.__name__ for mod in addon_utils.modules()}
        
        self.to_enable.clear()
        self.to_disable.clear()
        
        to_enable_modules = (required & all_installed) - current_enabled
        for name in to_enable_modules:
            item = self.to_enable.add()
            item.addon_name = name
        
        to_disable_modules = current_enabled - required
        for name in to_disable_modules:
            item = self.to_disable.add()
            item.addon_name = name
        
        if not self.to_enable and not self.to_disable:
            self.report({'INFO'}, "All dependencies match current settings.")
            return {'FINISHED'}
        
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def draw(self, context):
        layout = self.layout
        
        if self.to_enable:
            box = layout.box()
            box.label(text="Add-ons to Enable:", icon='ADD')
            for item in self.to_enable:
                box.label(text=item.addon_name)
        
        if self.to_disable:
            box = layout.box()
            box.label(text="Add-ons to Disable:", icon='REMOVE')
            for item in self.to_disable:
                box.label(text=item.addon_name)
        
        layout.prop(self, "action")
    
    def execute(self, context):
        if self.action == 'APPLY':
            for item in self.to_enable:
                bpy.ops.preferences.addon_enable(module=item.addon_name)
            for item in self.to_disable:
                bpy.ops.preferences.addon_disable(module=item.addon_name)
            self.report({'INFO'}, "Dependencies updated successfully.")
        
        context.window_manager.preset_dependencies.clear()
        return {'FINISHED'}

class PRESET_UL_PresetList(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if not os.path.exists(item.filepath):
            layout.label(text=f"MISSING: {item.name}", icon='CANCEL')
        else:
            layout.prop(item, "name", text="", emboss=False, icon='BLENDER')

class VIEW3D_PT_StartupPresets(Panel):
    bl_label = "Startup Template Presets"
    bl_idname = "VIEW3D_PT_startup_presets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Startup Presets"
    
    def draw(self, context):
        layout = self.layout
        prefs = get_preset_manager_data(context)
        
        row = layout.row()
        row.template_list("PRESET_UL_PresetList", "", prefs, "presets", prefs, "preset_index", rows=6)
        
        row = layout.row(align=True)
        row.operator(PRESET_OT_LoadPreset.bl_idname, text="Load Selected", icon='FILE_BLEND')
        row.operator(PRESET_OT_SavePreset.bl_idname, text="Save Current", icon='FILE_NEW')
        
        layout.separator()
        layout.operator(PRESET_OT_ScanFolder.bl_idname, text="Re-Scan Preset Folder", icon='FILE_REFRESH')

def scan_for_presets(context):
    prefs = get_preset_manager_data(context)
    presets_dir = get_runtime_presets_dir(context)
    prefs.presets.clear()
    
    if not os.path.exists(presets_dir):
        return
    
    for filename in os.listdir(presets_dir):
        if filename.lower().endswith(".blend"):
            filepath = os.path.join(presets_dir, filename)
            item = prefs.presets.add()
            item.filepath = filepath
            item.name = os.path.splitext(filename)[0]

@persistent
def load_post_handler(dummy):
    print("Startup Preset Manager: Running post-load scan.")
    scan_for_presets(bpy.context)
    
    # Load dependencies from the text block in the loaded file
    if load_dependencies_from_file(bpy.context):
        # Queue the dependency check if dependencies were found
        bpy.ops.preset.dependency_queue('INVOKE_DEFAULT')

classes = (
    PREDATA_PG_StartupPreset,
    PRESET_ManagerAddonPreferences,
    PRESET_OT_SavePreset,
    PRESET_OT_LoadPreset,
    PRESET_OT_ScanFolder,
    PRESET_OT_DependencyQueue,
    PRESET_OT_DependencyCheck,
    PRESET_UL_PresetList,
    VIEW3D_PT_StartupPresets,
)

def register():
    bpy.utils.register_class(PREDATA_PG_Dependency)
    bpy.types.WindowManager.preset_dependencies = bpy.props.CollectionProperty(type=PREDATA_PG_Dependency)
    
    for cls in classes:
        if cls is PREDATA_PG_Dependency:
            continue
        bpy.utils.register_class(cls)
    
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)

def unregister():
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    
    for cls in reversed(classes):
        if cls is PREDATA_PG_Dependency:
            continue
        bpy.utils.unregister_class(cls)
    
    del bpy.types.WindowManager.preset_dependencies
    bpy.utils.unregister_class(PREDATA_PG_Dependency)

if __name__ == "__main__":
    register()