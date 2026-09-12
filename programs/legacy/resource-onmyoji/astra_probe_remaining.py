exec(open(r'C:\Users\palla\Documents\resource\OnmyojiAPK\tools\astra_probe.py').read().split('rows=[]')[0])
for r in json.loads((R/'reports/astra_probe.json').read_text()):
 if 'args' not in r:
  d=Path(r['source']).read_bytes();print(r['sha256'][:8],d[:16].hex())
  for width in [False,True]:
   p.bones_is_16=lambda *a:width
   try:p.MeshParser0().parse(d)
   except Exception as e:print(width,type(e).__name__,str(e))
 else:
  if r.get('bad_indices'):
   d=Path(r['source']).read_bytes();o=r['face_offset'];n=r['args'][1];fc=r['args'][2]
   print(r['sha256'][:8], d[o-16:o+40].hex())
   for shift in range(-8,25,2):
    fa=struct.unpack_from('<%dH'%(3*fc),d,o+shift)
    print(shift,sum(v>=n for v in fa),max(fa),len(set(fa)))
