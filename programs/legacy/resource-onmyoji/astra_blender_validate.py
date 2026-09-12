import bpy,json
from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK')
m=json.loads((R/'converted/corpus_astra_shape_retry_v1/batch_manifest.json').read_text());rows=[]
for r in m['assets']:
 if r['status']!='converted':continue
 bpy.ops.wm.read_factory_settings(use_empty=True)
 result=bpy.ops.import_scene.gltf(filepath=r['output'])
 meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
 vertices=sum(len(o.data.vertices) for o in meshes);faces=sum(len(o.data.polygons) for o in meshes)
 assert 'FINISHED' in result and meshes,r['sha256']
 rows.append({'sha256':r['sha256'],'vertices':vertices,'faces':faces,'source_vertices':r['vertices'],'source_faces':r['faces'],'status':'passed'})
(R/'reports/astra_blender_validation.json').write_text(json.dumps({'blender_version':bpy.app.version_string,'passed':len(rows),'rows':rows},indent=2))
print('ALL PASSED',len(rows))
