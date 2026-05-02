# imports
import struct


class eSRT:
	SIZE_RENDER_STATE_BLOCK = 680
	SIZE_GEOM_DESCRIPTOR    = 40
	SIZE_LOD_TABLE_ENTRY    = 24
	SIZE_AUX_DATA_ENTRY     = 48
	SIZE_COLLISION_OBJECT   = 36

	VF_DESC_OFFSET          = 33
	VF_DESC_SIZE            = 13
	STRIDE_BYTE_OFFSET      = 663

	BILLBOARD_BLOB0_FACTOR  = 16
	BILLBOARD_FOOTER_SIZE   = 84

	ADDITIONAL_DATA_SIZE    = 31
	WIND_DATA_SIZE          = 1308

class SRTParser:
	def __init__(self, data):
		self.data = data
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

	def _read_string(self):
		start = self.pos
		while self.pos < len(self.data) and self.data[self.pos] != 0:
			self.pos += 1
		result = self.data[start:self.pos].decode('utf-8', errors='ignore')
		self.pos += 1
		return result

	def _align_to_4(self):
		while self.pos % 4 != 0:
			self.pos += 1


	def _parse_header(self):
		header = self._read_string()
		if header != "SRT 06.0.0":
			raise ValueError(f"Invalid header: {header}")
		self.pos = 16  # пропуск заполнения до границы 16 байт
		return {"header": header}

	def _parse_platform(self):
		self.endian_byte = self._read_byte()
		self.coord_system = self._read_byte()
		self.is_native_endian = self.endian_byte == 0
		self.endian = '<' if self.is_native_endian else '>'
		self._read_byte() # reserve?
		self._read_byte() # reserve?
		self.platform = {
			'endian_byte': self.endian_byte,
			'coord_system': self.coord_system,
			'is_native_endian': self.is_native_endian,
			'byte_order': 'little' if self.is_native_endian else 'big'
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
		lod_enabled = self._read_int()
		lod_data = [self._read_float() for _ in range(4)]
		return {"lod": {"enabled": bool(lod_enabled), "ranges": lod_data}}

	def _parse_wind(self):
		wind_data = self._read_bytes(eSRT.WIND_DATA_SIZE)
		return {"wind": wind_data}

	def _parse_additional(self):
		additional = self._read_bytes(eSRT.ADDITIONAL_DATA_SIZE)
		self._align_to_4()
		return {"additional": additional}

	def _parse_string_table_preamble(self):
		preamble = {
			"u32_0": self._read_int(),
			"u32_1": self._read_int(),
			"u32_2": self._read_int(),
			"f32_0": self._read_float(),
		}
		return {"string_table_preamble": preamble}

	def _parse_string_table(self):
		try:
			count = self._read_int()
			if count > 10000 or self.pos + count * 8 > len(self.data):
				return {"string_table": "Invalid count or insufficient data"}

			entries = []
			for _ in range(count):
				size_a = self._read_int()
				size_b = self._read_int()
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
			return {
				"string_table": {
					"count": count,
					"entries": entries,
					"strings": strings,
					"strings_base": strings_base,
					"total_string_bytes": total_string_bytes,
				}
			}
		except Exception:
			return {"string_table": "Parse error"}

	def _parse_collision_objects(self):
		try:
			count = self._read_int()
			if count > 1000 or self.pos + count * eSRT.SIZE_COLLISION_OBJECT > len(self.data):
				return {"collision_objects": "Invalid count or insufficient data"}
			objects = []
			for _ in range(count):
				objects.append(self._read_bytes(eSRT.SIZE_COLLISION_OBJECT))
			return {"collision_objects": {"count": count, "objects": objects}}
		except Exception:
			return {"collision_objects": "Parse error"}

	def _parse_billboards(self):
		try:
			origin = [self._read_float() for _ in range(3)]
			count0 = self._read_int()
			if count0 < 0:
				raise ValueError("Invalid billboard count0")

			blob0_size = eSRT.BILLBOARD_BLOB0_FACTOR * count0
			if self.pos + blob0_size > len(self.data):
				raise ValueError("Billboard blob0 out of range")
			blob0 = self._read_bytes(blob0_size)

			flags_size = count0
			if self.pos + flags_size > len(self.data):
				raise ValueError("Billboard flags out of range")
			raw_flags = self._read_bytes(flags_size)

			self._align_to_4()

			count1 = self._read_int()
			count2 = self._read_int()
			if count1 < 0 or count2 < 0:
				raise ValueError("Invalid billboard count1/count2")

			verts2d_blob = b""
			indices_blob = b""
			if count1 > 0 and count2 > 0:
				verts2d_size = 8 * count1
				indices_size = 2 * count2
				if self.pos + verts2d_size + indices_size > len(self.data):
					raise ValueError("Billboard secondary data out of range")
				verts2d_blob = self._read_bytes(verts2d_size)
				indices_blob = self._read_bytes(indices_size)
				self._align_to_4()

			footer = self._read_bytes(eSRT.BILLBOARD_FOOTER_SIZE)

			vertices2d = []
			for i in range(0, len(verts2d_blob), 8):
				x, y = struct.unpack(self.endian + '2f', verts2d_blob[i:i + 8])
				vertices2d.append((x, y))

			indices = []
			for i in range(0, len(indices_blob), 2):
				idx = struct.unpack(self.endian + 'H', indices_blob[i:i + 2])[0]
				indices.append(idx)

			return {
				"billboards": {
					"origin": origin,
					"count0": count0,
					"count1": count1,
					"count2": count2,
					"vertices2d": vertices2d,
					"indices": indices,
					"raw_flags": raw_flags,
					"blob0": blob0,
					"footer": footer,
				}
			}
		except Exception:
			return {"billboards": "Parse error"}

	def _parse_custom_data(self):
		if self.pos + 20 > len(self.data):
			return {"custom_data": "Parse error"}
		refs = [self._read_int() for _ in range(5)]
		return {"custom_data": {"string_refs": refs}}

	def _parse_render_states(self):
		try:
			if self.pos + 16 > len(self.data):
				return {"render_states": "Parse error"}
			state_count = self._read_int()
			has_secondary = self._read_int() == 1
			has_tertiary = self._read_int() == 1
			render_mode = self._read_int()

			if state_count < 0 or state_count > 4096:
				return {"render_states": "Invalid count"}

			block_size = eSRT.SIZE_RENDER_STATE_BLOCK
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

	def _parse_3d_geometry_descriptors(self):
		try:
			num_lods = self._read_int()
			if num_lods < 0 or num_lods > 256:
				return {"3d_geometry": "Invalid LOD count"}

			lod_table_base = self.pos
			lod_table_size = eSRT.SIZE_LOD_TABLE_ENTRY * num_lods
			if self.pos + lod_table_size > len(self.data):
				return {"3d_geometry": "LOD table out of range"}
			self.pos += lod_table_size

			lods = []
			for lod_idx in range(num_lods):
				lod_start = lod_table_base + lod_idx * eSRT.SIZE_LOD_TABLE_ENTRY
				lod_words = struct.unpack(
					self.endian + '6I',
					self.data[lod_start:lod_start + eSRT.SIZE_LOD_TABLE_ENTRY]
				)
				num_geoms = lod_words[0]
				aux_count = lod_words[3]
				if num_geoms < 0 or num_geoms > 4096:
					return {"3d_geometry": "Invalid geom count"}
				if aux_count < 0 or aux_count > 4096:
					return {"3d_geometry": "Invalid aux count"}

				if self.pos + num_geoms * eSRT.SIZE_GEOM_DESCRIPTOR > len(self.data):
					return {"3d_geometry": "Geom descriptors out of range"}

				geoms = []
				for geom_idx in range(num_geoms):
					geom_words = struct.unpack(
						self.endian + '10I',
						self._read_bytes(eSRT.SIZE_GEOM_DESCRIPTOR)
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
				aux_bytes = aux_count * eSRT.SIZE_AUX_DATA_ENTRY
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
		desc_start = eSRT.VF_DESC_SIZE * (semantic_id + eSRT.VF_DESC_OFFSET)
		if desc_start + eSRT.VF_DESC_SIZE > len(vf_block):
			return []
		desc = vf_block[desc_start:desc_start + eSRT.VF_DESC_SIZE]
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
			lod_idx = lod["lod"]
			for geom in lod["geoms"]:
				geom_idx = geom["geom"]
				rs_index = geom["render_state_index"]
				num_vertices = geom["num_vertices"]
				num_indices = geom["num_indices"]
				is_index_32 = geom["is_index_32"]

				if rs_index < 0 or rs_index >= len(self.render_states["blocks"]):
					continue
				vf_block = self.render_states["blocks"][rs_index]
				stride = vf_block[eSRT.STRIDE_BYTE_OFFSET]
				if stride <= 0:
					continue

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
						indices.append(struct.unpack(self.endian + 'I', index_blob[start:start + 4])[0])
					else:
						indices.append(struct.unpack(self.endian + 'H', index_blob[start:start + 2])[0])

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
					"lod": lod_idx,
					"geom": geom_idx,
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
		result.update(self._parse_wind())
		result.update(self._parse_additional())
		result.update(self._parse_string_table_preamble())
		result.update(self._parse_string_table())
		result.update(self._parse_collision_objects())
		result.update(self._parse_billboards())
		result.update(self._parse_custom_data())
		result.update(self._parse_render_states())
		result.update(self._parse_3d_geometry_descriptors())
		result.update(self._parse_vertex_index_data())
		return result