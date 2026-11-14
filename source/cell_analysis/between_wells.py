"""Exploratory within-acquisition well comparisons, executed in the existing SciPy runtime."""
import json, math, sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
import numpy as np
import tifffile
from scipy.stats import kruskal, rankdata, norm, false_discovery_control
from .seeding_density import calculate as density_comparison


def exclusion(feature):
    if 'ObjectNumber' in feature or feature.startswith(('Location_', 'Number_', 'AreaShape_Center_', 'AreaShape_BoundingBoxMinimum_', 'AreaShape_BoundingBoxMaximum_', 'AreaShape_SpatialMoment_')):
        return 'Identifiers and source coordinates are not biological comparison measures.'
    if feature == 'AreaShape_Orientation' or 'AngleBetween' in feature:
        return 'Angular measurements require a circular statistical test.'
    return ''


def rank_comparison(groups):
    """Kruskal–Wallis and tie-corrected Dunn two-sided contrasts."""
    names=sorted(groups); vals=[np.asarray(groups[n],float) for n in names]
    pooled=np.concatenate(vals); N=len(pooled)
    if len(np.unique(pooled))==1:
        return 0.,1.,[(a,b,1.) for a,b in combinations(names,2)]
    ranks=rankdata(pooled); _,counts=np.unique(pooled,return_counts=True)
    variance=N*(N+1)/12-sum(float(t)**3-t for t in counts)/(12*(N-1))
    start=0;means={}
    for name,v in zip(names,vals):
        means[name]=float(np.mean(ranks[start:start+len(v)]));start+=len(v)
    pairs=[]
    for a,b in combinations(names,2):
        z=abs(means[a]-means[b])/math.sqrt(variance*(1/len(groups[a])+1/len(groups[b])))
        pairs.append((a,b,float(2*norm.sf(z))))
    h,p=kruskal(*vals)
    return float(h),float(p),pairs


def calculate(data,selected='AreaShape_Area'):
    features=data['feature_names']
    if selected not in features:raise ValueError('Unknown measurement')
    observations=defaultdict(list)
    for c in data['observations']:observations[c['image_uid']].append(c)
    batches=defaultdict(list)
    for im in data['images']:batches[(im['export_path'],im['field_id'])].append(im)
    global_rows=[];well_rows=[];pair_rows=[]
    pair_family=sum(len(ims)*(len(ims)-1)//2 for ims in batches.values())*len(features)
    for (export,field),images in sorted(batches.items()):
        if len({im['well_id'] for im in images})!=len(images):raise ValueError('Multiple acquisitions of a well in one export/field; split into time points before comparison')
        key={'timepoint':export,'label':Path(export).name,'field_id':field,'from_time':min(i['time'] for i in images),'to_time':max(i['time'] for i in images)}
        by_well={}; blocks={}; errors={}
        for im in images:
            well=im['well_id'];by_well[well]=observations[im['image_uid']];blocks[well]=defaultdict(list)
            try:
                mask=tifffile.imread(Path(im['folder'])/'analysis_region.tif').astype(bool)
                if mask.ndim!=2:raise ValueError('Invalid mask dimensions')
                h,w=mask.shape
                for c in by_well[well]:
                    x=c['x_reference_px']-im['translation_x_px'];y=c['y_reference_px']-im['translation_y_px']
                    ix,iy=round(x),round(y)
                    if 0<=ix<w and 0<=iy<h and mask[iy,ix]:blocks[well][(min(3,int(x*4/w)),min(3,int(y*4/h)))].append(c)
            except (OSError,ValueError) as e:errors[well]=str(e)
        for feature in features:
            reason=exclusion(feature);groups={};summaries={}
            def finite(rows):
                out=[]
                for c in rows:
                    try:v=float(c.get(feature,''))
                    except (TypeError,ValueError):continue
                    if math.isfinite(v):out.append(v)
                return out
            for well,rows in by_well.items():
                vals=finite(rows);region=[finite(r) for r in blocks[well].values()]
                medians=[float(np.median(v)) for v in region if len(v)>=3]
                if len(medians)>=5 and not reason and well not in errors:groups[well]=medians
                summaries[well]={'well_id':well,'cell_count':len(rows),'finite_count':len(vals),'mean':float(np.mean(vals)) if vals else None,'median':float(np.median(vals)) if vals else None,'sd':float(np.std(vals,ddof=1)) if len(vals)>1 else None,'q25':float(np.percentile(vals,25)) if vals else None,'q75':float(np.percentile(vals,75)) if vals else None,'blocks':len(medians),'eligible':well in groups,'reason':reason or ('Valid analysis-region mask unavailable' if well in errors else '' if well in groups else 'Needs ≥5 regions with ≥3 cells per region')}
            result={**key,'feature':feature,'eligible_wells':len(groups),'total_wells':len(images),'H':None,'p':None,'q':None,'reason':reason or ('' if len(groups)>=2 else 'Fewer than two eligible wells')}
            if len(groups)>=2:
                if feature==selected:h,p,pairs=rank_comparison(groups)
                else:
                    vals=list(groups.values())
                    h,p=(0.,1.) if len(np.unique(np.concatenate(vals)))==1 else kruskal(*vals)
                result.update(H=float(h),p=float(p))
                if feature==selected:
                    for a,b,pair_p in pairs:
                        pair_rows.append({**key,'feature':feature,'well_a':a,'well_b':b,'median_difference_b_minus_a':summaries[b]['median']-summaries[a]['median'],'p':pair_p,'adjusted_p':min(1.,pair_p*pair_family)})
            global_rows.append(result)
            if feature==selected:well_rows.extend({**key,'feature':feature,**r} for r in summaries.values())
    if global_rows:
        qs=false_discovery_control([r['p'] if r['p'] is not None else 1 for r in global_rows],method='by')
        for r,q in zip(global_rows,qs):
            if r['p'] is not None:r['q']=float(q)
    return {'density_comparison':density_comparison(data),'feature':selected,'global':global_rows,'wells':well_rows,'pairs':pair_rows,'global_family':len(global_rows),'pair_family':pair_family,'notes':[
        'Each completed export is treated as one acquisition/time point; acquisition ranges are shown. Different fields are analyzed separately. Split exports containing multiple acquisition rounds first.',
        'Mean, median, SD and quartiles summarize all finite cell measurements in each image. Tests use medians from a fixed 4 × 4 spatial grid within the valid image region; ≥3 cells per region and ≥5 regions per well are required.',
        'Kruskal–Wallis tests rank distributions across eligible wells; it is not strictly a test of means or medians when distribution shapes differ. Dunn contrasts use pooled ranks and tie correction.',
        'Global p-values use Benjamini–Yekutieli FDR across all features, exports and fields. Pairwise p-values use Bonferroni across all planned well pairs, features, exports and fields, including unavailable tests.',
        'Exploratory image-level comparisons: regions may remain spatially dependent. Cells and regions are not independent biological replicates. Treatment effects require independent replicate wells/experiments and treatment labels.',
        'No significant difference is not evidence of equivalence. Missing wells and sparse fields are not assigned a zero value. Single-image cell counts are descriptive only.'
    ]}

if __name__=='__main__':
    payload=json.load(sys.stdin)
    json.dump(calculate(payload['analysis'],payload['feature']),sys.stdout,allow_nan=False)
