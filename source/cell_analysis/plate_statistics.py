"""Exploratory within-field changes, using paired spatial blocks rather than cells as replicates."""
from collections import defaultdict
from functools import lru_cache
import math
from pathlib import Path
import numpy as np
import tifffile
from .time_series import FEATURES

METHOD='Exact paired sign-flip test of mean spatial-block median change'

@lru_cache(maxsize=16)
def sign_matrix(n):
    return 1-2*((np.arange(2**n,dtype=np.uint32)[:,None]>>np.arange(n))&1).astype(float)

def sign_flip(differences):
    d=np.asarray(differences,dtype=float)
    if not len(d) or len(d)>16 or not np.all(np.isfinite(d)):raise ValueError('Expected 1–16 finite block differences')
    signs=sign_matrix(len(d))
    null=np.abs(signs@d/len(d)); observed=abs(float(d.mean()))
    return float(np.mean(null>=observed-1e-12))

def adjust_by(ps):
    """Benjamini–Yekutieli adjustment across the full requested test family."""
    p=np.asarray(ps,float);m=len(p)
    if not m:return []
    order=np.argsort(p);harmonic=sum(1/i for i in range(1,m+1))
    adjusted=np.minimum.accumulate((p[order]*m*harmonic/np.arange(1,m+1))[::-1])[::-1]
    out=np.empty(m);out[order]=np.minimum(adjusted,1);return out.tolist()

def calculate(analysis):
    images={i['image_uid']:i for i in analysis['images']};cells=defaultdict(list);series=defaultdict(list)
    for c in analysis['observations']:cells[c['image_uid']].append(c)
    for im in images.values():series[(im['well_id'],im['field_id'])].append(im)
    rows=[];features=analysis.get('feature_names',FEATURES)
    for (well,field),frames in sorted(series.items()):
        frames.sort(key=lambda x:x['time'])
        for a,b in zip(frames,frames[1:]):
            key=a['time'][:10]+' → '+b['time'][:10]
            base={'well_id':well,'field_id':field,'comparison':key,'from_time':a['time'],'to_time':b['time'],'from_image_uid':a['image_uid'],'to_image_uid':b['image_uid']}
            try:
                ma=tifffile.imread(Path(a['folder'])/'analysis_region.tif').astype(bool)
                mb=tifffile.imread(Path(b['folder'])/'analysis_region.tif').astype(bool)
                if ma.ndim!=2 or mb.shape!=ma.shape:raise ValueError('Different image dimensions')
            except (OSError,ValueError):
                rows.extend({**base,'feature':f,'status':'unavailable','reason':'Matching analysis-region masks required','p':None,'q':None} for f in features);continue
            h,w=ma.shape
            def blocks(frame):
                result=defaultdict(list);n=0
                for c in cells[frame['image_uid']]:
                    x,y=c['x_reference_px'],c['y_reference_px']
                    if not (0<=x<w and 0<=y<h):continue
                    eligible=True
                    for im,mask in [(a,ma),(b,mb)]:
                        ix=int(round(x-im['translation_x_px']));iy=int(round(y-im['translation_y_px']))
                        if not (0<=ix<w and 0<=iy<h and mask[iy,ix]):eligible=False;break
                    if eligible:result[(min(3,int(x*4/w)),min(3,int(y*4/h)))].append(c);n+=1
                return result,n
            aa,na=blocks(a);bb,nb=blocks(b)
            for feature in features:
                if 'ObjectNumber' in feature or feature.startswith(('AreaShape_SpatialMoment_', 'Location_','Number_','AreaShape_Center_','AreaShape_BoundingBoxMinimum_','AreaShape_BoundingBoxMaximum_')):
                    rows.append({**base,'feature':feature,'status':'unavailable','reason':'Object identifiers and source-coordinate measurements are not tested for biological change','p':None,'q':None});continue
                if feature in ('AreaShape_Orientation','Neighbors_AngleBetweenNeighbors_20'):
                    rows.append({**base,'feature':feature,'status':'unavailable','reason':'Angular measurements require a circular statistical test','p':None,'q':None});continue
                before=[];after=[]
                for block in sorted(aa.keys() & bb.keys()):
                    def values(group):
                        v=[]
                        for c in group:
                            try:x=float(c[feature])
                            except (ValueError,TypeError):continue
                            if math.isfinite(x):v.append(x)
                        return v
                    va,vb=values(aa[block]),values(bb[block])
                    if min(len(va),len(vb))>=3:before.append(float(np.median(va)));after.append(float(np.median(vb)))
                dif=np.asarray(after)-np.asarray(before);n=len(dif)
                effect=float(np.mean(dif)) if n else None
                baseline=float(np.mean(before)) if n else None
                rows.append({**base,'feature':feature,'n_cells_t1':na,'n_cells_t2':nb,'paired_blocks':n,'effect':effect,'percent_change':100*effect/baseline if baseline else None,'p':sign_flip(dif) if n>=6 else None,'q':None,'status':'tested' if n>=6 else 'insufficient','reason':'' if n>=6 else 'Requires ≥6 paired blocks with ≥3 cells per time point'})
    # Unavailable tests remain in the planned family as p=1: do not shrink correction after filtering.
    adjusted=adjust_by([r['p'] if r['p'] is not None else 1 for r in rows])
    for r,q in zip(rows,adjusted):
        if r['p'] is not None:r['q']=q
    return {'method':METHOD,'correction':'Benjamini–Yekutieli FDR','family_size':len(rows),'features':features,'alpha':.05,'rows':rows,'notes':[
        'Exploratory within-field screen, not biological replicate inference or a paired-cell test.',
        '4 × 4 fixed spatial blocks; ≥3 cells at each time and ≥6 paired blocks. Cell centroids must be in both valid image regions.',
        'Tests average change in block medians. Exact sign flips assume independent, symmetric block differences under the null; spatial dependence can still violate this assumption.',
        'FDR correction spans all wells, fields, adjacent time intervals and all computed features in the selected exports. Adding exports changes the test family.',
        'Blue/orange indicates q < 0.05 and direction of change. Gray means insufficient data; white means the threshold was not met, not proof of equivalence.',
        'Registration and segmentation remain unreviewed. Only a small field within each well is measured. No significance test is assigned to a single pair of total cell counts.'
    ]}
