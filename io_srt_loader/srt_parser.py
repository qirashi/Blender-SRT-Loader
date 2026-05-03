# imports
import struct


class CoordSysType:
	Y_UP_RIGHT = 0
	Z_UP_RIGHT = 1
	Y_UP_LEFT = 2
	Z_UP_LEFT = 3

class eSRTConstants:
	WIND_V6_DATA_SIZE           = 1308
	WIND_V7_DATA_SIZE           = 1308

	ADDITIONAL_V6_DATA_SIZE     = 31

	RENDER_STATE_V6_SIZE        = 680
	RENDER_STATE_V7_SIZE        = 804

	DRAW_CALL_SIZE              = 40
	LOD_TABLE_ENTRY_SIZE        = 24
	BONE_SIZE                   = 48
	COLLISION_OBJECT_SIZE       = 36

	VF_DESC_OFFSET              = 33
	VF_DESC_SIZE                = 13
	STRIDE_BYTE_OFFSET          = 663

	HORIZONTAL_BILLBOARD_SIZE   = 84  # 1 int + 20 floats

class SRTParser:
	def __init__(self, data):
		self.data = data
		self.version = None
		self.pos = 0
		self.endian = '<'
		self.is_native_endian = True
		self.platform = {}
		self.string_table_entries = []
		self.string_data_base = 0
		self.render_states = {"count": 0, "blocks": []}
		self.geometry_descriptors = {"num_lods": 0, "lods": []}

	def _read_bytes(self, size):
		if self.pos + size > len(self.data):
			raise ValueError(f"Premature end of file at position {self.pos}")
		result = self.data[self.pos:self.pos + size]
		self.pos += size
		return result

	def _read_int(self):
		return struct.unpack(self.endian + 'I', self._read_bytes(4))[0]

	def _read_float(self):
		return struct.unpack(self.endian + 'f', self._read_bytes(4))[0]

	def _read_byte(self):
		return self._read_bytes(1)[0]

	def _align_to_4(self):
		while self.pos % 4 != 0:
			self.pos += 1


	#  Top-level parse sections ---------------------------------------------------------
	def _parse_header(self):
		raw = self._read_bytes(16)

		header = raw.rstrip(b'\x00').decode('ascii')
		if header == "SRT 06.0.0":
			self.version = 6
		elif header == "SRT 07.0.0":
			self.version = 7
		else:
			raise ValueError(f"Unsupported SRT header: {header!r}")

		print(f"Header: {header}, version: {self.version}")
		return {"header": header, "version": self.version}

	def _parse_platform(self):
		"""Matches C++ CParser::ParsePlatform: endian byte, coord system, texcoords flipped, reserved"""
		self.endian_byte = self._read_byte()
		self.coord_system = self._read_byte()
		self.texcoords_flipped = self._read_byte() == 1
		self._read_byte()  # reserved

		self.is_native_endian = self.endian_byte == 0
		self.endian = '<' if self.is_native_endian else '>'

		self.platform = {
			'endian_byte': self.endian_byte,
			'coord_system': self.coord_system,
			'texcoords_flipped': self.texcoords_flipped,
			'is_native_endian': self.is_native_endian,
			'byte_order': 'little' if self.is_native_endian else 'big',
		}
		return {"platform": self.platform}

	def _parse_extents(self):
		extents = [self._read_float() for _ in range(6)]
		if extents[0] > extents[3]:
			extents[0], extents[3] = extents[3], extents[0]
		if extents[1] > extents[4]:
			extents[1], extents[4] = extents[4], extents[1]
		if extents[2] > extents[5]:
			extents[2], extents[5] = extents[5], extents[2]
		return {"extents": {"min": extents[:3], "max": extents[3:]}}

	def _parse_lod(self):
		"""Matches SLodProfile: enabled flag + 4 float distances"""
		lod_enabled = self._read_int()
		lod_data = [self._read_float() for _ in range(4)]
		return {"lod": {"enabled": bool(lod_enabled), "ranges": lod_data}}

	def _parse_wind_v6(self):
		"""Wind parameters blob of fixed size (covers SPairParams + options + tree data)"""
		wind_data = self._read_bytes(eSRTConstants.WIND_V6_DATA_SIZE)
		return {"wind": wind_data}

	def _parse_wind_v7(self):
		"""Wind parameters blob of fixed size (covers SPairParams + options + tree data)"""
		wind_data = self._read_bytes(eSRTConstants.WIND_V7_DATA_SIZE)
		return {"wind": wind_data}

	def _parse_additional_v6(self):
		additional = self._read_bytes(eSRTConstants.ADDITIONAL_V6_DATA_SIZE)
		self._align_to_4()
		return {"additional": additional}

	def _parse_string_table(self):
		"""Matches CParser::ParseStringTable: count, padded lengths, then string data."""
		try:
			if self.version == 6:
				preamble = {
					"u32_0": self._read_int(),
					"u32_1": self._read_int(),
					"u32_2": self._read_int(),
					"f32_0": self._read_float(),
				}
			else:
				preamble = None

			count = self._read_int()
			if count > 10000 or self.pos + count * 8 > len(self.data):
				return {"string_table": "Invalid count or insufficient data"}

			entries = []
			for _ in range(count):
				size_a = self._read_int()  # padding (4 bytes)
				size_b = self._read_int()  # actual string length
				entries.append({"size_a": size_a, "size_b": size_b})

			strings_base = self.pos
			strings = []
			total_string_bytes = 0
			for entry in entries:
				chunk_len = entry["size_b"]
				if chunk_len < 0 or self.pos + chunk_len > len(self.data):
					break
				raw_string = self._read_bytes(chunk_len)
				strings.append(raw_string.rstrip(b'\x00').decode('utf-8', errors='ignore'))
				total_string_bytes += chunk_len

			self._align_to_4()
			self.string_table_entries = entries
			self.string_data_base = strings_base

			result = {
				"string_table": {
					"count": count,
					"entries": entries,
					"strings": strings,
					"strings_base": strings_base,
					"total_string_bytes": total_string_bytes,
				}
			}
			if preamble is not None:
				result["string_table_preamble"] = preamble

			return result
		except Exception:
			return {"string_table": "Parse error"}

	def _parse_collision_objects(self):
		try:
			count = self._read_int()
			if count > 1000 or self.pos + count * eSRTConstants.COLLISION_OBJECT_SIZE > len(self.data):
				return {"collision_objects": "Invalid count or insufficient data"}
			objects = []
			for _ in range(count):
				objects.append(self._read_bytes(eSRTConstants.COLLISION_OBJECT_SIZE))
			return {"collision_objects": {"count": count, "objects": objects}}
		except Exception:
			return {"collision_objects": "Parse error"}


	#  Billboard parsing (matches C++ vertical + horizontal structures) ---------------------------------------------------------
	def _parse_billboards(self):
		"""Parse vertical billboards followed by horizontal billboard (formerly 'footer')"""
		try:
			# Vertical billboards header
			width = self._read_float()
			top = self._read_float()
			bottom = self._read_float()
			num_billboards = self._read_int()

			if num_billboards < 0 or num_billboards > 10000:
				return {"billboards": "Invalid vertical billboard count"}

			# Texcoord table: 4 floats per billboard
			texcoords_size = num_billboards * 4 * 4  # 4 floats * 4 bytes
			if self.pos + texcoords_size > len(self.data):
				return {"billboards": "Texcoord table out of range"}
			texcoords_blob = self._read_bytes(texcoords_size)
			texcoords = []
			for i in range(0, len(texcoords_blob), 16):
				tc = struct.unpack(self.endian + '4f', texcoords_blob[i:i+16])
				texcoords.append(tc)

			# Rotated flags (1 byte per billboard)
			if self.pos + num_billboards > len(self.data):
				return {"billboards": "Rotated flags out of range"}
			rotated_flags = self._read_bytes(num_billboards)
			self._align_to_4()

			# Cutout vertices and indices counts
			num_cutout_verts = self._read_int()
			num_cutout_indices = self._read_int()
			if num_cutout_verts < 0 or num_cutout_indices < 0:
				return {"billboards": "Invalid cutout counts"}

			cutout_vertices = []
			cutout_indices = []
			if num_cutout_verts > 0 and num_cutout_indices > 0:
				verts_size = num_cutout_verts * 2 * 4  # 2 floats per vertex
				if self.pos + verts_size > len(self.data):
					return {"billboards": "Cutout vertices out of range"}
				verts_blob = self._read_bytes(verts_size)
				for i in range(0, verts_size, 8):
					x, y = struct.unpack(self.endian + '2f', verts_blob[i:i+8])
					cutout_vertices.append((x, y))

				indices_size = num_cutout_indices * 2  # uint16
				if self.pos + indices_size > len(self.data):
					return {"billboards": "Cutout indices out of range"}
				indices_blob = self._read_bytes(indices_size)
				for i in range(0, indices_size, 2):
					idx = struct.unpack(self.endian + 'H', indices_blob[i:i+2])[0]
					cutout_indices.append(idx)
				self._align_to_4()

			# Horizontal billboard (previously called footer)
			horiz_size = eSRTConstants.HORIZONTAL_BILLBOARD_SIZE  # 1 int + 20 floats
			if self.pos + horiz_size > len(self.data):
				return {"billboards": "Horizontal billboard data out of range"}
			h_present = self._read_int()
			h_texcoords = [self._read_float() for _ in range(8)]
			h_positions = []
			for _ in range(4):
				h_positions.append(tuple(self._read_float() for _ in range(3)))

			return {
				"billboards": {
					"vertical": {
						"width": width,
						"top": top,
						"bottom": bottom,
						"num_billboards": num_billboards,
						"texcoords": texcoords,
						"rotated_flags": rotated_flags,
						"num_cutout_vertices": num_cutout_verts,
						"num_cutout_indices": num_cutout_indices,
						"cutout_vertices": cutout_vertices,
						"cutout_indices": cutout_indices,
					},
					"horizontal": {
						"present": bool(h_present),
						"texcoords": h_texcoords,
						"positions": h_positions,
					}
				}
			}
		except Exception:
			return {"billboards": "Parse error"}

	def _parse_custom_data(self):
		if self.pos + 20 > len(self.data):
			return {"custom_data": "Parse error"}
		refs = [self._read_int() for _ in range(5)]   # CCore::USER_STRING_COUNT = 5
		return {"custom_data": {"string_refs": refs}}


	#  Render states ---------------------------------------------------------
	def _parse_render_states(self):
		try:
			if self.version == 7:
				block_size = eSRTConstants.RENDER_STATE_V7_SIZE
			else:
				block_size = eSRTConstants.RENDER_STATE_V6_SIZE

			if self.pos + 16 > len(self.data):
				return {"render_states": "Parse error"}
			state_count = self._read_int()
			has_secondary = self._read_int() == 1 # depth-only pass
			has_tertiary = self._read_int() == 1  # shadow-cast pass
			render_mode = self._read_int()        # shader path index

			if state_count < 0 or state_count > 4096:
				return {"render_states": "Invalid count"}

			primary_size = state_count * block_size
			if self.pos + primary_size > len(self.data):
				return {"render_states": "Primary block out of range"}
			primary_base = self.pos
			self.pos += primary_size

			secondary_base = None
			tertiary_base = None
			if has_secondary:
				if self.pos + primary_size > len(self.data):
					return {"render_states": "Secondary block out of range"}
				secondary_base = self.pos
				self.pos += primary_size
			if has_tertiary:
				if self.pos + primary_size > len(self.data):
					return {"render_states": "Tertiary block out of range"}
				tertiary_base = self.pos
				self.pos += primary_size

			copy_count = 1 + int(has_secondary) + int(has_tertiary)
			for _ in range(copy_count):
				if self.pos + block_size > len(self.data):
					return {"render_states": "State copy out of range"}
				self.pos += block_size

			blocks = []
			for i in range(state_count):
				start = primary_base + i * block_size
				blocks.append(self.data[start:start + block_size])
			self.render_states = {"count": state_count, "blocks": blocks}

			return {
				"render_states": {
					"count": state_count,
					"has_secondary": has_secondary,
					"has_tertiary": has_tertiary,
					"render_mode": render_mode,
					"primary_base": primary_base,
					"secondary_base": secondary_base,
					"tertiary_base": tertiary_base,
					"blocks": blocks,
				}
			}
		except Exception as exc:
			return {"render_states": f"Parse error: {exc}"}


	#  3D geometry descriptors (SLod + SDrawCall + SBone) ---------------------------------------------------------
	def _parse_3d_geometry_descriptors(self):
		try:
			num_lods = self._read_int()
			if num_lods < 0 or num_lods > 256:
				return {"3d_geometry": "Invalid LOD count"}

			lod_table_base = self.pos
			lod_table_size = eSRTConstants.LOD_TABLE_ENTRY_SIZE * num_lods
			if self.pos + lod_table_size > len(self.data):
				return {"3d_geometry": "LOD table out of range"}
			self.pos += lod_table_size

			lods = []
			for lod_idx in range(num_lods):
				lod_start = lod_table_base + lod_idx * eSRTConstants.LOD_TABLE_ENTRY_SIZE
				lod_words = struct.unpack(
					self.endian + '6I',
					self.data[lod_start:lod_start + eSRTConstants.LOD_TABLE_ENTRY_SIZE]
				)
				num_geoms = lod_words[0]      # m_nNumDrawCalls
				aux_count = lod_words[3]      # m_nNumBones

				if num_geoms < 0 or num_geoms > 4096:
					return {"3d_geometry": "Invalid geom count"}
				if aux_count < 0 or aux_count > 4096:
					return {"3d_geometry": "Invalid aux count"}

				if self.pos + num_geoms * eSRTConstants.DRAW_CALL_SIZE > len(self.data):
					return {"3d_geometry": "Geom descriptors out of range"}

				geoms = []
				for geom_idx in range(num_geoms):
					geom_words = struct.unpack(
						self.endian + '10I',
						self._read_bytes(eSRTConstants.DRAW_CALL_SIZE)
					)
					geoms.append({
						"geom": geom_idx,
						"render_state_index": geom_words[2],
						"num_vertices": geom_words[3],
						"num_indices": geom_words[6],
						"is_index_32": bool(geom_words[7] & 0xFF),
						"raw_words": list(geom_words),
					})

				aux_data = []
				aux_bytes = aux_count * eSRTConstants.BONE_SIZE
				if aux_count > 0:
					if self.pos + aux_bytes > len(self.data):
						return {"3d_geometry": "LOD aux data out of range"}
					aux_data = self._read_bytes(aux_bytes).hex()

				lods.append({
					"lod": lod_idx,
					"num_geoms": num_geoms,
					"aux_count": aux_count,
					"lod_words": list(lod_words),
					"geoms": geoms,
					"aux_data": aux_data,
				})

			self.geometry_descriptors = {"num_lods": num_lods, "lods": lods}
			return {"3d_geometry": {"num_lods": num_lods, "lods": lods}}
		except Exception as e:
			return {"3d_geometry": f"Parse error: {e}"}


	#  Vertex data decoding helpers ---------------------------------------------------------
	@staticmethod
	def _read_half_float(buf, endian):
		return struct.unpack(endian + 'e', buf)[0]

	def _decode_component(self, raw, comp_type):
		if comp_type == 0 and len(raw) >= 4:
			return struct.unpack(self.endian + 'f', raw[:4])[0]
		if comp_type == 1 and len(raw) >= 2:
			return self._read_half_float(raw[:2], self.endian)
		if comp_type == 2 and len(raw) >= 1:
			return (raw[0] / 255.0) * 2.0 - 1.0
		return 0.0

	def _decode_semantic(self, vertex_blob, base, stride, vf_block, semantic_id):
		desc_start = eSRTConstants.VF_DESC_SIZE * (semantic_id + eSRTConstants.VF_DESC_OFFSET)
		if desc_start + eSRTConstants.VF_DESC_SIZE > len(vf_block):
			return []
		desc = vf_block[desc_start:desc_start + eSRTConstants.VF_DESC_SIZE]
		comp_type = desc[0]

		component_count = sum(1 for c in desc[1:5] if c != 0xFF)
		if component_count <= 0:
			return []
		offsets = []
		for off in desc[9:13]:
			if off == 0xFF or off >= stride:
				continue
			offsets.append(off)
			if len(offsets) >= component_count:
				break

		values = []
		component_size = 4 if comp_type == 0 else 2 if comp_type == 1 else 1
		for off in offsets:
			data_start = base + off
			if data_start + component_size > len(vertex_blob):
				values.append(0.0)
				continue
			raw = vertex_blob[data_start:data_start + component_size]
			values.append(self._decode_component(raw, comp_type))
		return values


	#  Final vertex & index data ---------------------------------------------------------
	def _parse_vertex_index_data(self):
		raw_offset = self.pos
		raw = self.data[raw_offset:]
		meshes = []

		if not self.geometry_descriptors.get("lods"):
			return {
				"vertex_index_data": {
					"raw": raw.hex(),
					"raw_offset": raw_offset,
					"remaining_size": len(raw),
					"meshes": meshes,
				},
			}

		for lod in self.geometry_descriptors["lods"]:
			for geom in lod["geoms"]:
				rs_index = geom["render_state_index"]
				if rs_index < 0 or rs_index >= len(self.render_states["blocks"]):
					continue
				vf_block = self.render_states["blocks"][rs_index]

				if self.version == 7:
					stride = struct.unpack(self.endian + 'I', vf_block[0:4])[0]
				else:
					stride = vf_block[eSRTConstants.STRIDE_BYTE_OFFSET]
				if stride <= 0:
					continue

				num_vertices = geom["num_vertices"]
				num_indices = geom["num_indices"]
				is_index_32 = geom["is_index_32"]

				vertex_blob_size = num_vertices * stride
				if self.pos + vertex_blob_size > len(self.data):
					continue
				vertex_blob = self.data[self.pos:self.pos + vertex_blob_size]
				self.pos += vertex_blob_size

				index_size = 4 if is_index_32 else 2
				index_blob_size = num_indices * index_size
				if self.pos + index_blob_size > len(self.data):
					continue
				index_blob = self.data[self.pos:self.pos + index_blob_size]
				self.pos += index_blob_size

				self._align_to_4()

				indices = []
				for i in range(num_indices):
					start = i * index_size
					if index_size == 4:
						indices.append(struct.unpack(self.endian + 'I', index_blob[start:start+4])[0])
					else:
						indices.append(struct.unpack(self.endian + 'H', index_blob[start:start+2])[0])

				vertices = []
				for v_idx in range(num_vertices):
					base = v_idx * stride
					pos_values = self._decode_semantic(vertex_blob, base, stride, vf_block, 0)
					nrm_values = self._decode_semantic(vertex_blob, base, stride, vf_block, 1)

					uv_values = self._decode_semantic(vertex_blob, base, stride, vf_block, 3)
					if len(uv_values) < 2:
						uv_values = self._decode_semantic(vertex_blob, base, stride, vf_block, 10)
					if len(uv_values) < 2:
						uv_values = self._decode_semantic(vertex_blob, base, stride, vf_block, 14)
					if len(pos_values) < 3:
						pos_values = list(struct.unpack(self.endian + '3f', vertex_blob[base:base + 12]))
					if len(nrm_values) < 3:
						nrm_values = [0.0, 0.0, 1.0]
					if len(uv_values) < 2:
						uv_values = [0.0, 0.0]

					vertices.append({
						"pos": tuple(pos_values[:3]),
						"normal": tuple(nrm_values[:3]),
						"uv": (uv_values[0], uv_values[1]),
					})

				meshes.append({
					"lod": lod["lod"],
					"geom": geom["geom"],
					"num_vertices": num_vertices,
					"num_indices": num_indices,
					"stride": stride,
					"render_state_index": rs_index,
					"vertices": vertices,
					"indices": indices,
					"index_size": index_size,
				})

		return {
			"vertex_index_data": {
				"raw_offset": raw_offset,
				"remaining_size": len(raw),
				"final_offset": self.pos,
				"meshes": meshes,
			},
		}

	def parse(self):
		result = {}
		result.update(self._parse_header())
		result.update(self._parse_platform())
		result.update(self._parse_extents())
		result.update(self._parse_lod())
		if self.version == 7:
			result.update(self._parse_wind_v7())
		elif self.version == 6:
			result.update(self._parse_wind_v6())
			result.update(self._parse_additional_v6())
		result.update(self._parse_string_table())
		result.update(self._parse_collision_objects())
		result.update(self._parse_billboards())
		result.update(self._parse_custom_data())
		result.update(self._parse_render_states())
		result.update(self._parse_3d_geometry_descriptors())
		result.update(self._parse_vertex_index_data())
		return result