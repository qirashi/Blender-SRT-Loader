bl_info = {
	"name": "SRT Loader (.srt)",
	"author": "Qirashi",
	"version": (1, 0, 0),
	"blender": (4, 5, 0),
	"location": "File > Import",
	"description": "Import .srt files version 06.0.0.",
	"doc_url": "https://github.com/",
	"category": "Import-Export",
}

import math
import struct
import mathutils  # type: ignore
from pathlib import Path

import bpy  # type: ignore
from bpy.props import StringProperty  # type: ignore
from bpy_extras.io_utils import ImportHelper  # type: ignore

from .srt_parser import SRTParser


def _is_main_texture(name):
	if not isinstance(name, str):
		return False
	name = name.lower()
	if not name.endswith('.dds'):
		return False
	if any(x in name for x in ('_nm.', '_sm.', '_dam.', '_dnm.', '_spec.', '_rough.', '_metal.')):
		return False
	return True


def _resolve_texture_path(base_dir, texture_name):
	if not texture_name:
		return None
	tex_path = Path(texture_name)
	if tex_path.is_absolute():
		return tex_path if tex_path.exists() else None
	candidate = base_dir / texture_name
	return candidate if candidate.exists() else None


def _make_material_from_image(image_path, mat_name):
	if mat_name in bpy.data.materials:
		return bpy.data.materials[mat_name]
	mat = bpy.data.materials.new(mat_name)
	mat.use_nodes = True
	mat.blend_method = 'HASHED'
	mat.use_backface_culling = False
	mat.alpha_threshold = 0.5

	nodes = mat.node_tree.nodes
	links = mat.node_tree.links
	nodes.clear()

	output = nodes.new(type='ShaderNodeOutputMaterial')
	bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
	tex_node = nodes.new(type='ShaderNodeTexImage')

	bsdf.inputs['Roughness'].default_value = 1.0
	bsdf.inputs['Metallic'].default_value = 1.0

	if image_path:
		try:
			tex_node.image = bpy.data.images.load(str(image_path))
			if tex_node.image:
				tex_node.image.colorspace_settings.name = 'sRGB'
				links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
				links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
		except Exception:
			bsdf.inputs['Alpha'].default_value = 1.0
	else:
		bsdf.inputs['Alpha'].default_value = 1.0

	links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
	return mat


def _render_state_texture_indices(render_state_block):
	if not render_state_block or len(render_state_block) < 12:
		return []
	try:
		return list(struct.unpack('<3I', render_state_block[:12]))
	except Exception:
		return []


def create_materials_from_render_states(string_table, render_states, base_dir):
	materials = {}
	strings = []
	if string_table and isinstance(string_table, dict):
		strings = string_table.get('strings', [])

	if not render_states or not isinstance(render_states, dict):
		return materials

	blocks = render_states.get('blocks', [])
	for rs_index, block in enumerate(blocks):
		indices = _render_state_texture_indices(block)
		main_tex = None
		for idx in indices:
			if 0 <= idx < len(strings):
				name = strings[idx]
				if _is_main_texture(name):
					main_tex = name
					break
		if main_tex is None:
			for idx in indices:
				if 0 <= idx < len(strings):
					name = strings[idx]
					if isinstance(name, str) and name.lower().endswith('.dds'):
						main_tex = name
						break
		if main_tex is None:
			continue
		image_path = _resolve_texture_path(base_dir, main_tex)
		mat_name = Path(main_tex).stem
		mat = _make_material_from_image(image_path, mat_name)
		materials[rs_index] = mat
	return materials


def create_mesh_from_3d(mesh_data, name, target_collection=None, rotation=None):
	vertices = mesh_data.get('vertices', [])
	indices = mesh_data.get('indices', [])
	if not vertices or not indices or len(indices) % 3 != 0:
		return None
	verts = [v['pos'] for v in vertices]
	max_index = len(verts) - 1
	faces = []
	for i in range(0, len(indices), 3):
		tri = indices[i:i + 3]
		if len(tri) < 3:
			continue
		i0, i1, i2 = tri
		if (
			not isinstance(i0, int) or not isinstance(i1, int) or not isinstance(i2, int) or
			i0 < 0 or i1 < 0 or i2 < 0 or
			i0 > max_index or i1 > max_index or i2 > max_index
		):
			continue
		faces.append((i2, i1, i0))

	if not faces:
		return None

	mesh = bpy.data.meshes.new(name + "_mesh")
	try:
		mesh.from_pydata(verts, [], faces)
	except Exception:
		return None
	mesh.update()
	uv_layer = mesh.uv_layers.new(name="UVMap")
	for poly in mesh.polygons:
		for loop_idx in poly.loop_indices:
			vertex_idx = mesh.loops[loop_idx].vertex_index
			if 0 <= vertex_idx < len(vertices):
				u, v = vertices[vertex_idx]['uv']
				uv_layer.data[loop_idx].uv = (u, 1.0 - v)

	custom_normals = []
	for i in range(len(mesh.vertices)):
		src = vertices[i] if i < len(vertices) else {}
		n = src.get('normal', (0.0, 0.0, 1.0))
		if len(n) < 3:
			n = (0.0, 0.0, 1.0)
		custom_normals.append((float(n[0]), float(n[1]), float(n[2])))
	if custom_normals:
		try:
			mesh.normals_split_custom_set_from_vertices(custom_normals)
		except Exception:
			pass

	obj = bpy.data.objects.new(name, mesh)

	if rotation:
		obj.rotation_euler = rotation

	if target_collection is None:
		target_collection = bpy.context.collection
	target_collection.objects.link(obj)
	return obj


def get_or_create_collection(name, parent=None):
	col = bpy.data.collections.get(name)
	if col is None:
		col = bpy.data.collections.new(name)
		if parent is None:
			bpy.context.scene.collection.children.link(col)
		else:
			parent.children.link(col)
	return col


class IMPORT_OT_scots_pine_srt(bpy.types.Operator, ImportHelper):
	bl_idname = "import_scene.scots_pine_srt"
	bl_label = "Import SpeedTree SRT 06.0.0"
	bl_description = "Import SRT file and build available LOD geometry in Blender"
	bl_options = {'REGISTER', 'UNDO'}
	filename_ext = ".srt"
	filter_glob: StringProperty(default="*.srt", options={'HIDDEN'})  # type: ignore

	def execute(self, context):
		srt_path = Path(self.filepath)
		if not srt_path.exists():
			self.report({'ERROR'}, f"SRT file not found at {srt_path}")
			return {'CANCELLED'}

		parser = SRTParser(str(srt_path))
		try:
			parsed = parser.parse()
		except Exception as exc:
			self.report({'ERROR'}, f"Failed to parse SRT: {exc}")
			return {'CANCELLED'}

		base_name = srt_path.stem
		vertex_index = parsed.get('vertex_index_data', {})
		meshes = vertex_index.get('meshes', [])
		string_table = parsed.get('string_table')
		render_states = parsed.get('render_states')
		materials = create_materials_from_render_states(string_table, render_states, srt_path.parent)

		root_collection = get_or_create_collection(f"{base_name}_SRT")

		# Group meshes by LOD
		lods_dict = {}
		for mesh_data in meshes:
			lod = mesh_data.get('lod', 0)
			rs_index = mesh_data.get('render_state_index')
			if not materials or rs_index not in materials:
				continue
			if lod not in lods_dict:
				lods_dict[lod] = []
			lods_dict[lod].append((mesh_data, rs_index))

		created_objects = 0

		for lod in sorted(lods_dict.keys()):
			lod_collection = get_or_create_collection(f"{base_name}_LOD{lod}", parent=root_collection)
			lod_collection.hide_viewport = False
			lod_collection.hide_render = False
			lod_geoms = lods_dict[lod]

			geom_objects = []
			for mesh_data, rs_index in lod_geoms:
				geom = mesh_data.get('geom', 0)
				rotation_x_90 = mathutils.Euler((math.radians(90), 0, 0), 'XYZ')
				obj = create_mesh_from_3d(
					mesh_data,
					f"{base_name}_lod{lod}_geom{geom}",
					target_collection=lod_collection,
					rotation=rotation_x_90
				)
				if obj:
					obj.data.materials.append(materials[rs_index])
					geom_objects.append(obj)

			if not geom_objects:
				continue

			if len(geom_objects) > 1:
				bpy.ops.object.select_all(action='DESELECT')
				for obj in geom_objects:
					obj.select_set(True)
				context.view_layer.objects.active = geom_objects[0]
				bpy.ops.object.join()
				combined_obj = geom_objects[0]
				bpy.ops.object.select_all(action='DESELECT')
			else:
				combined_obj = geom_objects[0]

			combined_obj.name = f"{base_name}_LOD{lod}"
			combined_obj.hide_set(False)
			combined_obj.hide_render = False
			created_objects += 1
			self.report({'INFO'}, f"LOD {lod} created with {len(geom_objects)} geoms combined.")

		if created_objects == 0:
			self.report({'ERROR'}, "Parsed file but could not construct any geometry.")
			return {'CANCELLED'}

		return {'FINISHED'}


def menu_func_import(self, context):
	self.layout.operator(IMPORT_OT_scots_pine_srt.bl_idname, text="SpeedTree SRT (.srt)")


classes = (
	IMPORT_OT_scots_pine_srt,
)


def register():
	for cls in classes:
		bpy.utils.register_class(cls)
	bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
	bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)