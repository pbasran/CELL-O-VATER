"""Manual point references; mask intersections are candidates, never confirmed matches."""
import json,math,uuid,io
from pathlib import Path
from datetime import datetime,timezone
from functools import lru_cache
import numpy as np
import tifffile
from PIL import Image
from .profiles import BASE

def context():
    settings=json.loads((BASE/'local_settings.json').read_text())
    run=(BASE/settings['review_run']).resolve()
    if not run.is_relative_to((BASE/'outputs').resolve()):raise ValueError('Invalid review run')
    manifest=json.loads((run/'segmentation_manifest.json').read_text())
    if manifest['status']!='complete':raise ValueError('Run is not complete')
    return run,manifest

@lru_cache(maxsize=3)
def arrays(run,index):
    path=Path(run)
    manifest=json.loads((path/'segmentation_manifest.json').read_text())
    image=manifest['images'][index]
    return tifffile.imread(path/image['mask_relative_path']),tifffile.imread(path/f'analysis_regions/{index:06d}.tif').astype(bool)

def load(index):
    run,m=context();image=m['images'][index]
    path=run/f'manual-review-{index:06d}.json'
    return json.loads(path.read_text()) if path.exists() else {'revision':0,'points':[],'image_uid':image['image_uid'],'run_uid':m['run_uid'],'coordinate_space':'registered_reference_pixels'}

def clean_outlines(items,point_ids,shape):
    if not isinstance(items,list) or len(items)>2000:raise ValueError('Invalid outline list')
    result=[];seen=set()
    for item in items:
        point_id=item.get('point_id')
        if point_id not in point_ids:continue  # Removing a mark also removes its linked outline.
        if point_id in seen:raise ValueError('Only one outline per mark')
        seen.add(point_id);vertices=item.get('vertices')
        if not isinstance(vertices,list) or not 3<=len(vertices)<=128:raise ValueError('Use 3 to 128 outline vertices')
        for vertex in vertices:
            if not isinstance(vertex,list) or len(vertex)!=2:raise ValueError('Invalid outline vertex')
            x,y=vertex
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vertex):raise ValueError('Invalid outline coordinates')
            if not 0<=x<shape[1] or not 0<=y<shape[0]:raise ValueError('Outline outside image')
        if len({tuple(v) for v in vertices})!=len(vertices):raise ValueError('Outline has duplicate vertices')
        n=len(vertices)
        def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i in range(n):
            for j in range(i+1,n):
                if j==i+1 or (i==0 and j==n-1):continue
                a,b=vertices[i],vertices[(i+1)%n];c,d=vertices[j],vertices[(j+1)%n]
                if cross(a,b,c)*cross(a,b,d)<=0 and cross(c,d,a)*cross(c,d,b)<=0 and max(min(a[0],b[0]),min(c[0],d[0]))<=min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1]))<=min(max(a[1],b[1]),max(c[1],d[1])):raise ValueError('Outline edges cross; trace around the perimeter in order')
        area=abs(sum(vertices[i][0]*vertices[(i+1)%n][1]-vertices[(i+1)%n][0]*vertices[i][1] for i in range(n)))/2
        if area<1:raise ValueError('Outline area is too small')
        result.append({'point_id':point_id,'vertices':vertices,'polygon_area_px2':area,'source':'manual_user_trace','boundary_status':'user_drawn_unvalidated'})
    return result

def save(index,data):
    run,m=context();old=load(index)
    if data.get('revision')!=old['revision']:raise ValueError('Review changed elsewhere. Reload before editing.')
    points=data.get('points');mask,valid=arrays(str(run),index)
    if not isinstance(points,list) or len(points)>2000:raise ValueError('Invalid point list')
    clean=[];seen=set()
    for p in points:
        x,y=p.get('x'),p.get('y');uid=p.get('id')
        if not isinstance(uid,str) or len(uid)>64 or uid in seen:raise ValueError('Invalid point ID')
        seen.add(uid)
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in [x,y]):raise ValueError('Invalid coordinates')
        if not 0<=x<mask.shape[1] or not 0<=y<mask.shape[0]:raise ValueError('Point outside image')
        if p.get('confidence') not in ['high','low']:raise ValueError('Select high or low confidence')
        label=int(mask[int(y),int(x)])
        clean.append({'id':uid,'x':x,'y':y,'confidence':p['confidence'],'mask_label_at_point':label or None,'inside_analysis_region':bool(valid[int(y),int(x)])})
    outlines=clean_outlines(data.get('outlines',old.get('outlines',[])),seen,mask.shape)
    result={**old,'outlines':outlines,'revision':old['revision']+1,'points':clean,'updated_at':datetime.now(timezone.utc).isoformat(),'annotation_type':'manual_cell_center','matching_note':'A mask at a marked point is a candidate correspondence, not a validated cell boundary or detection match.'}
    target=run/f'manual-review-{index:06d}.json';tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2)+'\n');tmp.replace(target)
    return result

def image(index,overlay=False):
    run,m=context()
    if overlay:return (run/m['images'][index]['overlay_relative_path']).read_bytes(),'image/png'
    plane=tifffile.imread(run/f'registered_images/{index:06d}.tif');_,valid=arrays(str(run),index)
    lo,hi=np.percentile(plane[valid],[1,99]);a=np.uint8(np.clip((plane-lo)/max(float(hi-lo),1e-6)*255,0,255))
    b=io.BytesIO();Image.fromarray(a).save(b,format='PNG');return b.getvalue(),'image/png'
