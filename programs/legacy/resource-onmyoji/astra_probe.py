import sys,json,inspect,struct,math,collections
from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK')
sys.path[:0]=[str(R/'tools/NeoXtractor-source-v3.2'),str(R/'tools')]
import core.mesh_loader.parsers.new_parser as p
orig=p.identify_mesh_type
rows=[]
for item in json.loads((R/'converted/corpus_all_v4extended_colorized/failures.json').read_text()):
 d=Path(item['source']).read_bytes(); row={'sha256':item['sha256'],'source':item['source']}
 def capture(*a):
  frame=inspect.currentframe().f_back; off=frame.f_locals['f'].tell();row.update(args=a,offset=off)
  n,fc=a[1:3]
  if off+24*n+2<=len(d):
   pos=struct.unpack_from('<%df'%(n*3),d,off);norm=struct.unpack_from('<%df'%(n*3),d,off+12*n)
   flag=struct.unpack_from('<H',d,off+24*n)[0];foff=off+24*n+2+(12*n if flag==1 else flag*4)
   row.update(flag=flag,pos_finite=all(math.isfinite(v) for v in pos),pos_max=max(map(abs,pos)),normal_good=sum(.8<sum(v*v for v in norm[i:i+3])<1.2 for i in range(0,len(norm),3))/n,face_offset=foff)
   if foff+6*fc<=len(d):
    faces=struct.unpack_from('<%dH'%(3*fc),d,foff);row.update(face_max=max(faces),bad_indices=sum(v>=n for v in faces))
  return orig(*a)
 p.identify_mesh_type=capture
 try:p.MeshParser0().parse(d)
 except Exception as e:row['error']=str(e)
 rows.append(row)
(R/'reports/astra_probe.json').write_text(json.dumps(rows,indent=2))
print(collections.Counter(r.get('error','ok') for r in rows))
print('valid geometry',sum(r.get('bad_indices',1)==0 and r.get('normal_good',0)>.98 and r.get('pos_max',1e30)<1e6 for r in rows))
for r in rows:print(r['sha256'][:8],r.get('args'),r.get('flag'),r.get('pos_max'),r.get('normal_good'),r.get('bad_indices'),r.get('error'))
