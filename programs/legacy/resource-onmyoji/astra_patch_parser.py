from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK')
p=R/'tools/NeoXtractor-source-v3.2/core/mesh_loader/parsers/new_parser.py'
s=p.read_text();(R/'reports/new_parser_before_astra.py').write_text(s)
s=s.replace('import io\n','import io\nimport math\n')
s=s.replace('    def _parse_mesh_testing(self, f: BinaryIO) -> dict[str, Iterable[Any] | int]:','''    def parse_shape_only(self, data: bytes) -> MeshData:
        """Opt-in v4 geometry recovery; never infer unknown UV/skin layouts."""
        return self._standardize_mesh_data(
            self._parse_mesh_testing(io.BytesIO(data), shape_only=True)
        )

    def _parse_mesh_testing(self, f: BinaryIO, *, shape_only: bool = False) -> dict[str, Iterable[Any] | int]:''')
s=s.replace('        read_uint16(f)  # always_0x0500','''        if shape_only and model["version"] != 4:
            raise NotImplementedError("Shape-only recovery requires version 4")
        read_uint16(f)  # always_0x0500''')
s=s.replace('        mesh_data_size = ending_address - f.tell()','''        if shape_only:
            self._validate_vertex_count(vertex_count)
            self._validate_face_count(face_count)
            if meshes_inside != 1 or model["bones"]["has_bones"] not in (0, 1):
                raise NotImplementedError("Unsupported shape-only header")
        mesh_data_size = ending_address - f.tell()''')
s=s.replace('        if type == 100:\n','''        if shape_only:
            # Only standard float32 geometry is supported by this opt-in path.
            type = 101

        if type == 100:
''',1)
s=s.replace('        if _flag == 1 and (type == 4','''        if shape_only and _flag not in (0, 1):
            raise ValueError("Unknown shape-only vertex auxiliary flag")

        if _flag == 1 and (type == 4''')
s=s.replace('        model["mesh"]["face"] = []','''        if shape_only and f.tell() + face_count * 6 > ending_address:
            raise ValueError("Shape-only face block crosses mesh boundary")
        model["mesh"]["face"] = []''')
s=s.replace('        if type == 21:\n','''        if shape_only:
            positions = model["mesh"]["position"]
            normals = model["mesh"]["normal"]
            faces = model["mesh"]["face"]
            if not all(math.isfinite(v) and abs(v) < 1e6 for row in positions for v in row):
                raise ValueError("Invalid shape-only positions")
            if not all(math.isfinite(v) for row in normals for v in row):
                raise ValueError("Invalid shape-only normals")
            good_normals = sum(0.8 < sum(v*v for v in row) < 1.2 for row in normals)
            if good_normals / vertex_count < 0.99:
                raise ValueError("Shape-only normals do not corroborate float32 layout")
            if any(v >= vertex_count for face in faces for v in face):
                raise ValueError("Shape-only face index outside vertex range")
            if not any(len(set(face)) == 3 for face in faces):
                raise ValueError("Shape-only topology is entirely degenerate")
            model["mesh"]["uv"] = [(0.0, 0.0)] * vertex_count
            model["bones"] = {"has_bones": 0}
            return model

        if type == 21:
''',1)
p.write_text(s)
