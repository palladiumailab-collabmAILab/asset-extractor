import sys,json,importlib.util,struct,pickle
from pathlib import Path
R=Path(r'C:\Users\palla\Documents\resource\OnmyojiAPK');sys.path.insert(0,str(R/'tools/NeoXtractor-source-v3.2'))
from core.mesh_loader.parsers.new_parser import MeshParser0
spec=importlib.util.spec_from_file_location('before_astra',R/'reports/new_parser_before_astra.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
m=json.loads((R/'converted/corpus_all_v4extended_colorized/batch_manifest.json').read_text());assets=[r for r in m['assets'] if r['status']!='failed'];tested=0
for row in assets[::max(1,len(assets)//32)]:
 data=Path(row['source']).read_bytes()
 a=old.MeshParser0().parse(data);b=MeshParser0().parse(data)
 assert pickle.dumps(a)==pickle.dumps(b)
 tested+=1
r=json.loads((R/'reports/astra_probe.json').read_text())[0];data=Path(r['source']).read_bytes();rejections=[]
for name,off,fmt,value in [('normal',r['offset']+12*r['args'][1],'<f',float('nan')),('index',r['face_offset'],'<H',65535),('flag',r['offset']+24*r['args'][1],'<H',2),('version',4,'<H',3)]:
 d=bytearray(data);struct.pack_into(fmt,d,off,value)
 try:MeshParser0().parse_shape_only(bytes(d))
 except Exception as e:rejections.append({'case':name,'error':str(e)})
 else:raise AssertionError(name)
(R/'reports/astra_parser_validation.json').write_text(json.dumps({'baseline_regression_samples':tested,'corruption_rejections':rejections},indent=2))
print(tested,rejections)
