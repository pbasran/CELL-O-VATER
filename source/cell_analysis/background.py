"""Versioned, batch-scoped manual background references. Preview only."""
import json,uuid,io,hashlib
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import tifffile
from PIL import Image,ImageDraw
from . import review
from .profiles import BASE

SCALE=4
WINDOW=9
ILLUMINATION_WINDOW=65

def boxmean(a,size):
    radius=size//2
    z=np.pad(a.astype(np.float64),radius,mode='reflect')
    integral=np.pad(z,((1,0),(1,0))).cumsum(0).cumsum(1)
    return (integral[size:,size:]-integral[:-size,size:]-integral[size:,:-size]+integral[:-size,:-size])/(size*size)

def entropy_map(raw,bounds):
    lo,hi=bounds
    q=np.minimum((np.clip((raw-lo)/max(hi-lo,1e-6),0,1)*32).astype(np.uint8),31)
    result=np.zeros(raw.shape,np.float64)
    for level in range(32):
        p=boxmean(q==level,WINDOW)
        result-=p*np.log2(np.maximum(p,1e-12))
    return result

def source(index):
    run,m=review.context()
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(m['images']):raise ValueError('Invalid image index')
    image=m['images'][index]
    return run,m,image,tifffile.imread(run/f'registered_images/{index:06d}.tif')

def batch_members(image):
    settings=json.loads((BASE/'local_settings.json').read_text());manifest=json.loads(Path(settings['last_import']).read_text())
    ref=next((im for im in manifest['images'] if im['image_uid']==image['image_uid']),None)
    if ref is None:raise ValueError('Reference image is not in the current dataset')
    def signature(im):
        ac=im.get('acquisition',{})
        return {'date':(ac.get('acquisition_local_time') or '')[:10], 'source_folder':str(Path(im['image_relative_path']).parent),'imaging_source':im.get('imaging_source'),'device':im.get('imaging_metadata',{}),'magnification':ac.get('objective_magnification'),'shape':im.get('shape'),'dtype':im.get('dtype')}
    sig=signature(ref)
    if not sig['date']:raise ValueError('Acquisition date is unknown; cannot assign batch automatically')
    members=[im['image_uid'] for im in manifest['images'] if signature(im)==sig]
    return {'dataset_uid':manifest['dataset_uid'],'signature':sig,'member_image_uids':members,'member_count':len(members),'qualification':'Matching available metadata only. User confirms medium and illumination consistency; missing metadata cannot establish equivalence.'}

def save(index,rect,confirmed,provenance='manual_rectangle'):
    if confirmed is not True:raise ValueError('Confirm the region is cell-free and settings are consistent within the batch')
    run,m,image,plane=source(index)
    if not isinstance(rect,list) or len(rect)!=4 or any(isinstance(v,bool) or not isinstance(v,int) for v in rect):raise ValueError('Rectangle must contain four integer coordinates')
    x,y,w,h=rect
    if min(w,h)<64 or x<0 or y<0 or x+w>plane.shape[1] or y+h>plane.shape[0]:raise ValueError('Select a region at least 64 × 64 pixels inside the image')
    _,valid=review.arrays(str(run),index)
    if not valid[y:y+h,x:x+w].all():raise ValueError('Reference overlaps the fiducial or excluded image area')
    annotation=review.load(index)
    if any(x<=p['x']<x+w and y<=p['y']<y+h for p in annotation['points']):raise ValueError('Reference contains an existing cell mark')
    for o in annotation.get('outlines',[]):
        v=np.asarray(o['vertices'])-[x,y]
        if v[:,0].max()<0 or v[:,1].max()<0 or v[:,0].min()>=w or v[:,1].min()>=h:continue
        bitmap=Image.new('1',(w,h));ImageDraw.Draw(bitmap).polygon([tuple(t) for t in v],fill=1)
        if np.asarray(bitmap).any():raise ValueError('Reference overlaps a saved cell outline')
    roi=plane[y:y+h,x:x+w];bounds=np.percentile(roi,[1,99]).tolist()
    if bounds[1]-bounds[0]<1e-6:raise ValueError('Reference has no usable intensity variation')
    sampled=roi[::SCALE,::SCALE];ent=entropy_map(sampled,bounds);margin=WINDOW//2;interior=ent[margin:-margin,margin:-margin]
    profile={'profile_uid':str(uuid.uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),'source_image_uid':image['image_uid'],'source_sha256':image['source_sha256'],'registered_roi_sha256':hashlib.sha256(roi.tobytes()).hexdigest(),'run_uid':m['run_uid'],'index':index,'rectangle_xywh':rect,'coordinate_space':'registered_reference_pixels','confirmed_cell_free':True,'provenance':provenance,'batch':batch_members(image),'batch_conditions_confirmed':provenance=='manual_rectangle','features':{'intensity_bounds':bounds,'mean':float(roi.mean()),'std':float(roi.std()),'mean_gradient':float(np.hypot(*np.gradient(roi.astype(float))).mean()),'entropy_5_95':np.percentile(interior,[5,95]).tolist()},'preview_method':{'sampling_step':SCALE,'entropy_window':WINDOW,'quantization_bins':32,'preservation_margin_source_px':8},'status':'experimental_preview_only','automatic_suppression':False}
    directory=run/'background-profiles';directory.mkdir(exist_ok=True)
    (directory/(profile['profile_uid']+'.json')).write_text(json.dumps(profile,indent=2)+'\n')
    return profile

def latest(index):
    run,_,image,_=source(index);files=sorted((run/'background-profiles').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in files:
        profile=json.loads(path.read_text())
        if image['image_uid'] in profile['batch']['member_image_uids']:return profile
    return None

def illumination_residual(small,valid):
    """Remove broad additive shading; excluded pixels do not contribute."""
    weights=boxmean(valid,ILLUMINATION_WINDOW)
    field=boxmean(np.where(valid,small,0),ILLUMINATION_WINDOW)/np.maximum(weights,1e-12)
    return np.where(valid,small-field,0)

def texture_features(residual):
    """Contrast and edge evidence at preview resolution, without cell annotations."""
    mean=boxmean(residual,5)
    contrast=np.sqrt(np.maximum(boxmean(residual*residual,5)-mean*mean,0))
    # Smooth single-pixel noise before measuring local edge energy.
    dy,dx=np.gradient(boxmean(residual,3))
    edges=np.sqrt(np.maximum(boxmean(dx*dx+dy*dy,5),0))
    return {'local_contrast':contrast,'edge_strength':edges}

def feature_match(features,limits):
    match=np.ones(next(iter(features.values())).shape,bool)
    for name,values in features.items():
        low,high=limits[name]
        match &= (values>=low)&(values<=high)
    return match

def outline_overlap(background,annotation):
    """Evaluate full-resolution outline interiors against the preview mask."""
    full=np.repeat(np.repeat(background,SCALE,0),SCALE,1)
    total=overlap=touched=count=0
    for outline in annotation.get('outlines',[]):
        vertices=np.asarray(outline['vertices'])
        x0,y0=np.maximum(np.floor(vertices.min(0)).astype(int),0)
        x1,y1=np.minimum(np.ceil(vertices.max(0)).astype(int)+1,[full.shape[1],full.shape[0]])
        if x1<=x0 or y1<=y0:continue
        bitmap=Image.new('1',(int(x1-x0),int(y1-y0)))
        ImageDraw.Draw(bitmap).polygon([tuple(p) for p in vertices-[x0,y0]],fill=1)
        inside=np.asarray(bitmap);n=int((inside&full[y0:y1,x0:x1]).sum())
        total+=int(inside.sum());overlap+=n;touched+=n>0;count+=1
    return {'outlines_checked':count,'outlines_touching_blue':touched,'outlined_pixel_fraction_in_blue':overlap/total if total else None}

def display_bounds(valid):
    yy,xx=np.nonzero(valid)
    if not len(xx):raise ValueError('Image has no valid viewing area')
    x,y=int(xx.min()),int(yy.min())
    return [x,y,int(xx.max())+1-x,int(yy.max())+1-y]

def display_image(index):
    run,_,_,_=source(index)
    _,valid=review.arrays(str(run),index)
    x,y,w,h=display_bounds(valid)
    original=Image.open(io.BytesIO(review.image(index)[0]))
    buf=io.BytesIO();original.crop((x,y,x+w,y+h)).save(buf,format='PNG')
    return buf.getvalue()

def preview(index,method='raw'):
    if method not in {'raw','illumination','combined'}:raise ValueError('Unknown background preview method')
    profile=latest(index)
    if profile is None:raise ValueError('Select and save a background region for this batch first')
    run,_,_,plane=source(index);_,valid=review.arrays(str(run),index);small=plane[::SCALE,::SCALE];v=valid[::SCALE,::SCALE]
    bounds=profile['features']['intensity_bounds'];low,high=profile['features']['entropy_5_95']
    if method in {'illumination','combined'}:
        # Calibrate on the saved reference image with exactly the same full-image processing.
        ref_run,_,ref_image,ref=source(profile['index'])
        if ref_image['image_uid']!=profile['source_image_uid']:raise ValueError('Saved reference image no longer matches this run')
        _,ref_valid=review.arrays(str(ref_run),profile['index'])
        residual=illumination_residual(ref[::SCALE,::SCALE],ref_valid[::SCALE,::SCALE])
        x,y,w,h=profile['rectangle_xywh'];margin=WINDOW//2
        ys=slice((y+SCALE-1)//SCALE+margin,(y+h-1)//SCALE+1-margin)
        xs=slice((x+SCALE-1)//SCALE+margin,(x+w-1)//SCALE+1-margin)
        bounds=np.percentile(residual[ys,xs],[1,99]).tolist()
        if bounds[1]-bounds[0]<1e-6:raise ValueError('Reference has no usable texture after illumination correction')
        low,high=np.percentile(entropy_map(residual,bounds)[ys,xs],[5,95])
        small_features=illumination_residual(small,v)
    else:small_features=small
    entropy=entropy_map(small_features,bounds)
    feature_limits={}
    # Entropy windows touching excluded pixels cannot establish background texture.
    supported=boxmean(v,WINDOW)>1-1e-9
    background=(entropy>=low)&(entropy<=high)&v&supported
    if method=='combined':
        reference_features=texture_features(residual)
        feature_limits={name:np.percentile(values[ys,xs],[5,95]).tolist() for name,values in reference_features.items()}
        background &= feature_match(texture_features(small_features),feature_limits)
    # Preserve a border around pixels with non-background entropy. This is deliberately a preview, not a cell detector.
    candidates=(~background)&v;expanded=candidates.copy();pad=np.pad(candidates,2)
    for dy in range(5):
        for dx in range(5):expanded|=pad[dy:dy+v.shape[0],dx:dx+v.shape[1]]
    background &= ~expanded
    lo,hi=np.percentile(plane[valid],[1,99]);gray=np.uint8(np.clip((small-lo)/max(hi-lo,1e-6),0,1)*255);rgb=np.repeat(gray[...,None],3,axis=2);rgb[background]=(rgb[background]*.45+np.array([40,100,255])*.55).astype(np.uint8)
    x,y,w,h=display_bounds(v)
    buf=io.BytesIO();Image.fromarray(rgb[y:y+h,x:x+w]).save(buf,format='PNG')
    stats={'profile_uid':profile['profile_uid'],'method':method,'method_version':3,'feature_limits':feature_limits,'illumination_window_source_px':ILLUMINATION_WINDOW*SCALE if method in {'illumination','combined'} else None,'quantization_bounds':bounds,'entropy_5_95':[float(low),float(high)],'background_like_valid_fraction':float(background[v].mean()),'note':'Blue is background-like texture, not confirmed empty area. Review before any suppression. No masks or measurements changed.'}
    annotation=review.load(index)
    marked=annotation.get('points',[])
    stats['marked_centers_in_background_preview']=sum(bool(background[min(int(p['y']/SCALE),background.shape[0]-1),min(int(p['x']/SCALE),background.shape[1]-1)]) for p in marked)
    stats['marked_centers_checked']=len(marked)
    stats['marked_centers_by_confidence']={level:{'in_blue':sum(bool(background[min(int(p['y']/SCALE),background.shape[0]-1),min(int(p['x']/SCALE),background.shape[1]-1)]) for p in marked if p.get('confidence')==level),'total':sum(p.get('confidence')==level for p in marked)} for level in ('high','low')}
    stats.update(outline_overlap(background,annotation))
    stats['calibration_note']='Saved reference retained. Correction removes broad additive shading only; it does not correct all illumination-dependent noise.'
    return buf.getvalue(),stats
