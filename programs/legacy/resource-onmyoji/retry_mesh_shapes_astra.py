"""Retry known corpus failures using opt-in validated v4 shape-only parsing.
Original files and the baseline corpus are read-only. UV/skin omitted deliberately.
"""
from pathlib import Path
import sys,json,hashlib,base64,struct
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools/NeoXtractor-source-v3.2'),str(ROOT/'tools')]
from core.mesh_loader.parsers.new_parser import MeshParser0
from core.mesh_converter.formats import gltf
from batch_convert_mesh_corpus import validate_mesh
OUT=ROOT/'converted/corpus_astra_shape_retry_v1'

def accessor(doc,index):
 a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
 b=base64.b64decode(doc['buffers'][v['buffer']]['uri'].split(',',1)[1])
 count=a['count']*{'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
 fmt={5126:'f',5123:'H',5125:'I'}[a['componentType']]
 return struct.unpack_from('<'+str(count)+fmt,b,v.get('byteOffset',0)+a.get('byteOffset',0))

def main():
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'gltf').mkdir(exist_ok=True)
 failures=json.loads((ROOT/'converted/corpus_all_v4extended_colorized/failures.json').read_text())
 results=[]
 for item in failures:
  row={**item,'output':None,'recovery':'validated_v4_float32_geometry_only','omitted':['UV coordinates','skeleton','vertex joints','vertex weights','original materials/textures']}
  try:
   data=Path(item['source']).read_bytes()
   assert hashlib.sha256(data).hexdigest()==item['sha256'],'source hash mismatch'
   m=MeshParser0().parse_shape_only(data);validate_mesh(m)
   doc=json.loads(gltf.convert(m))
   rgb=[.3+int(item['sha256'][i:i+2],16)/255*.6 for i in (0,2,4)]
   doc['materials']=[{'name':'NeoXColorizedFallback','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':rgb+[1.0],'metallicFactor':0,'roughnessFactor':.82}}]
   doc['extras']={'recovery':row['recovery'],'source_sha256':item['sha256'],'omitted':row['omitted']}
   for entry in doc['meshes']:
    for prim in entry['primitives']:prim['material']=0
   prim=doc['meshes'][0]['primitives'][0]
   assert accessor(doc,prim['attributes']['POSITION'])==tuple(v for xyz in m.mesh.position for v in xyz)
   assert accessor(doc,prim['attributes']['NORMAL'])==tuple(v for xyz in m.mesh.normal for v in xyz)
   assert accessor(doc,prim['indices'])==tuple(v for face in m.mesh.face for v in face)
   assert not doc.get('skins') and 'JOINTS_0' not in prim['attributes']
   path=OUT/'gltf'/(item['sha256'][:16]+'__'+Path(item['source']).stem+'.gltf')
   payload=json.dumps(doc,separators=(',',':'),allow_nan=False).encode()
   tmp=path.with_suffix('.tmp');tmp.write_bytes(payload);tmp.replace(path)
   assert hashlib.sha256(Path(item['source']).read_bytes()).hexdigest()==item['sha256']
   row.update(status='converted',output=str(path),vertices=m.vertex_count,faces=m.face_count,bytes=len(payload),verification='exported float32 positions/normals and indices exactly equal parsed source blocks; source SHA-256 unchanged')
   row.pop('error',None);row.pop('error_type',None)
  except Exception as e:row.update(status='failed',error_type=type(e).__name__,error=str(e))
  results.append(row)
 manifest={'source_policy':'read-only','baseline_gltf':21540,'retry_selected':len(results),'counts':{s:sum(r['status']==s for r in results) for s in ['converted','failed']},'assets':results}
 manifest['combined_gltf']=21540+manifest['counts']['converted']
 (OUT/'batch_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 (OUT/'failures.json').write_text(json.dumps([r for r in results if r['status']=='failed'],indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in manifest.items() if k!='assets'},indent=2))
if __name__=='__main__':main()
