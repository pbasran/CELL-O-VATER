"""Executed only in the isolated Cellpose environment, with a prepared run specification."""
import csv
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import uuid
import zipfile
import time


def save(path,data):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.replace(path)


def run(spec_path, model_cache=None):
    started=time.perf_counter();timings={"images":[]}
    model_cache={} if model_cache is None else model_cache
    spec=json.loads(Path(spec_path).read_text());out=Path(spec['output_directory'])
    os.environ['CELLPOSE_LOCAL_MODELS_PATH']=spec['model_directory']
    import numpy as np
    import tifffile
    import torch
    from PIL import Image,ImageDraw
    from cellpose import models,utils
    from registration import align_to_reference
    import cv2
    torch.set_num_threads(max(1,min(4,os.cpu_count() or 1)))
    options=spec['options'];total=len(spec['frames'])
    def progress(stage,completed,message):save(out/'progress.json',dict(stage=stage,completed=completed,total=total,message=message))
    if options.get('register_fiducial'):
        failures=[]
        for index,frame in enumerate(spec['frames']):
            progress('checking_fiducials',index,f"Checking marker in {frame['source_path']}")
            plane=np.load(out/frame['input_relative_path'],allow_pickle=False)
            try:align_to_reference(plane)
            except ValueError as exc:failures.append(f"{frame['source_path']}: {exc}")
        if failures:
            save(out/'registration_review.json',{'status':'needs_review','images':failures})
            raise ValueError('Marker check failed before segmentation: '+'; '.join(failures))
    timings['runtime_and_preflight_seconds']=time.perf_counter()-started
    model_started=time.perf_counter()
    progress('loading_model',0,'Loading or reusing Cellpose model')
    sam=options['model']=='cpsam_v2'
    key=(str(Path(spec['model_directory']).resolve()),options['model'])
    reused=key in model_cache
    if not reused:
        model=models.CellposeModel(gpu=False,pretrained_model='cpsam_v2',use_bfloat16=False) if sam else models.CellposeModel(gpu=False,model_type=options['model'])
        checksum=hashlib.sha256(Path(model.pretrained_model).read_bytes()).hexdigest()
        model_cache[key]=(model,checksum)
    model,checksum=model_cache[key]
    timings['model_load_and_hash_seconds']=time.perf_counter()-model_started
    timings['model_reused']=reused
    run={'run_uid':spec['run_uid'],'engine':'Cellpose','engine_version':importlib.metadata.version('cellpose'),
         'torch_version':torch.__version__,'device':'cpu','model':options['model'],'model_sha256':checksum,
         'options':options,'started_at':datetime.now(timezone.utc).isoformat(),'status':'running',
         'identity_scope':'Object IDs are local to this segmentation run. Cell tracking and parent/daughter assignment have not been performed.',
         'measurement_status':'CellProfiler not connected','images':[],'object_count':0}
    for subdir in ['masks','overlays','registered_images','analysis_regions']:(out/subdir).mkdir()
    references={}
    columns=['well_id','field_id','coordinate_space','run_uid','image_uid','source_path','frame_index','object_uid','mask_label','mask_relative_path','mask_pixel_count','centroid_x_px','centroid_y_px','touches_image_border']
    with (out/'segmented_objects.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns);writer.writeheader()
        for index,frame in enumerate(spec['frames']):
            progress('segmenting',index,f"Segmenting {frame['source_path']} · frame {frame['frame_index']}")
            image_started=time.perf_counter()
            plane=np.load(out/frame['input_relative_path'],allow_pickle=False)
            registration=None;valid=np.ones(plane.shape,dtype=bool)
            if options.get('exclude_black_border') and not options.get('register_fiducial'):
                from field_of_view import field_mask
                valid=field_mask(plane)
            if options.get('register_fiducial'):
                key=frame['sequence_uid']
                if key not in references and frame.get('reference_source_image_uid')!=frame['source_image_uid']:
                    raise ValueError('The reference acquisition must be included before later images')
                reference=references.get(key)
                if reference and plane.shape!=reference['shape']:raise ValueError('Time-series image dimensions differ')
                plane,valid,registration=align_to_reference(plane,reference['center'] if reference else None)
                if reference is None:
                    references[key]={'center':(registration['center_x_px'],registration['center_y_px']),'shape':plane.shape,'image_uid':frame['image_uid']}
                registration['reference_image_uid']=references[key]['image_uid']
                tifffile.imwrite(out/f'registered_images/{index:06d}.tif',plane,photometric='minisblack',metadata={'axes':'YX'})
                tifffile.imwrite(out/f'analysis_regions/{index:06d}.tif',valid.astype(np.uint8),photometric='minisblack',metadata={'axes':'YX'})
            tifffile.imwrite(out/f'registered_images/{index:06d}.tif',plane,photometric='minisblack')
            tifffile.imwrite(out/f'analysis_regions/{index:06d}.tif',valid.astype(np.uint8),photometric='minisblack')
            inference=plane.copy();inference[~valid]=np.median(plane[valid])
            inference_started=time.perf_counter()
            if sam:
                yy,xx=np.nonzero(valid);x0,x1=int(xx.min()),int(xx.max())+1;y0,y1=int(yy.min()),int(yy.max())+1
                labels,_,_=model.eval(inference[y0:y1,x0:x1],batch_size=1,diameter=options['diameter'] or None,
                    flow_threshold=options['flow_threshold'],cellprob_threshold=options['cellprob_threshold'],min_size=options['min_size'],
                    normalize={'tile_norm_blocksize':options.get('tile_norm_blocksize',0)},niter=options.get('niter') or None)
                masks=np.zeros(plane.shape,np.uint32);masks[y0:y1,x0:x1]=labels
            else:
                masks,flows,styles=model.eval(inference,channels=[0,0],diameter=options['diameter'],
                    flow_threshold=options['flow_threshold'],cellprob_threshold=options['cellprob_threshold'],
                    min_size=options['min_size'],do_3D=False,
                    normalize={'tile_norm_blocksize':options.get('tile_norm_blocksize',0)},niter=options.get('niter') or None)
            inference_seconds=time.perf_counter()-inference_started
            post_started=time.perf_counter()
            if masks.shape!=plane.shape:raise RuntimeError('Cellpose mask dimensions do not match the input plane')
            masks=masks.astype(np.uint32)
            excluded_labels=np.unique(masks[~valid]);excluded_labels=excluded_labels[excluded_labels!=0]
            if len(excluded_labels):masks[np.isin(masks,excluded_labels)]=0
            mask_name=f'masks/{index:06d}_labels.tif';overlay_name=f'overlays/{index:06d}.png'
            tifffile.imwrite(out/mask_name,masks,photometric='minisblack',metadata={'axes':'YX'})
            lo,hi=np.percentile(plane,[1,99]);gray=np.uint8(np.clip((plane-lo)/max(float(hi-lo),1e-6)*255,0,255))
            rgb=np.repeat(gray[:,:,None],3,axis=2);rgb[utils.masks_to_outlines(masks)]=[46,232,171]
            if registration:
                boundary=cv2.morphologyEx(valid.astype(np.uint8),cv2.MORPH_GRADIENT,np.ones((3,3),np.uint8)).astype(bool)
                rgb[boundary]=[255,160,0]
            overlay=Image.fromarray(rgb);draw=ImageDraw.Draw(overlay)
            labels=np.unique(masks);labels=labels[labels!=0]
            for label in labels:
                y,x=np.nonzero(masks==label)
                object_uid=str(uuid.uuid5(uuid.UUID(spec['run_uid']),frame['image_uid']+':'+str(label)))
                border=bool((x==0).any() or (y==0).any() or (x==masks.shape[1]-1).any() or (y==masks.shape[0]-1).any())
                writer.writerow(dict(well_id=frame.get('well_id'),field_id=frame.get('field_id'),coordinate_space='registered_reference' if registration else 'source_image',run_uid=spec['run_uid'],image_uid=frame['image_uid'],source_path=frame['source_path'],
                    frame_index=frame['frame_index'],object_uid=object_uid,mask_label=int(label),mask_relative_path=mask_name,
                    mask_pixel_count=len(x),centroid_x_px=float(x.mean()),centroid_y_px=float(y.mean()),touches_image_border=border))
                draw.text((float(x.mean()),float(y.mean())),str(label),fill='yellow',stroke_width=1,stroke_fill='black')
            handle.flush();overlay.save(out/overlay_name)
            run['images'].append({**{k:v for k,v in frame.items() if k!='input_relative_path'},
                'mask_relative_path':mask_name,'overlay_relative_path':overlay_name,'object_count':len(labels),
                'registration':registration,'excluded_object_count':len(excluded_labels)})
            run['object_count']+=len(labels)
            save(out/'segmentation_manifest.json',run)
            timings['images'].append({'source':frame['source_path'],'preprocessing_seconds':inference_started-image_started,'inference_seconds':inference_seconds,'output_seconds':time.perf_counter()-post_started})
            save(out/'worker_timing.json',timings)
            progress('segmenting',index+1,f'Completed {index+1} of {total} images')
    run.update(status='complete',completed_at=datetime.now(timezone.utc).isoformat())
    save(out/'segmentation_manifest.json',run)
    archive_started=time.perf_counter()
    with zipfile.ZipFile(out/'segmentation_results.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [out/'segmented_objects.csv',out/'segmentation_manifest.json',out/'import_manifest.json',out/'job_spec.json',*sorted((out/'masks').glob('*.tif')),*sorted((out/'overlays').glob('*.png')),*sorted((out/'registered_images').glob('*.tif')),*sorted((out/'analysis_regions').glob('*.tif'))]:
            archive.write(path,path.relative_to(out))
    timings['archive_seconds']=time.perf_counter()-archive_started
    timings['total_seconds']=time.perf_counter()-started
    save(out/'worker_timing.json',timings)
    progress('complete',total,'Segmentation complete')

if __name__=='__main__' and sys.argv[1]=='--serve':
    cache={}
    for line in sys.stdin:
        spec_path=json.loads(line);out=Path(spec_path).parent
        try:
            run(spec_path,cache);save(out/'worker_done.json',{'status':'complete'})
        except Exception as exc:
            import traceback
            traceback.print_exc();cache.clear()
            save(out/'failure.json',{'status':'failed','error':str(exc)})
            save(out/'worker_done.json',{'status':'failed','error':str(exc)})
elif __name__=='__main__':
    try:run(sys.argv[1])
    except Exception as exc:
        import traceback
        traceback.print_exc()
        spec=json.loads(Path(sys.argv[1]).read_text())
        save(Path(spec['output_directory'])/'failure.json',{'error':str(exc),'status':'failed'})
        raise SystemExit(1)
