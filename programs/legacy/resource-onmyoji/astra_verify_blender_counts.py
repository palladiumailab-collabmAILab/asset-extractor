import json,sys
from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK');sys.path.insert(0,str(R/'tools'))
from retry_mesh_shapes_astra import accessor
p=R/'reports/astra_blender_validation.json';report=json.loads(p.read_text());m=json.loads((R/'converted/corpus_astra_shape_retry_v1/batch_manifest.json').read_text());items={r['sha256']:r for r in m['assets']}
for r in report['rows']:
 d=json.loads(Path(items[r['sha256']]['output']).read_text());ix=accessor(d,d['meshes'][0]['primitives'][0]['indices']);deg=len(ix)//3-len({tuple(sorted(ix[i:i+3])) for i in range(0,len(ix),3) if len(set(ix[i:i+3]))==3});r['source_degenerate_or_duplicate_triangles']=deg
 assert r['vertices']==r['source_vertices'] and r['faces']==r['source_faces']-deg,r
report['all_vertex_counts_exact']=True;report['all_face_count_differences_explained_by_degenerate_or_duplicate_source_triangles']=True
p.write_text(json.dumps(report,indent=2));print('Verified',len(report['rows']),'degenerate triangles',sum(r['source_degenerate_or_duplicate_triangles'] for r in report['rows']))
