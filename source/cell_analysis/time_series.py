"""Read-only assembly of completed exports and provisional cross-time candidates."""
import csv
import hashlib
import json
import math
from .coverage import measure_coverage
from datetime import datetime
from pathlib import Path

FEATURES=['AreaShape_Area','AreaShape_Perimeter','AreaShape_Eccentricity','Intensity_MeanIntensity_Source']

def discover(root):
    root=Path(root).expanduser().resolve()
    if not root.is_dir():raise ValueError('Results search folder does not exist')
    exports=[]
    for marker in sorted(root.rglob('COMPLETE.json')):
        if any(x.startswith('.') or x in {'0_RawData','backups','time_series'} for x in marker.relative_to(root).parts):continue
        folder=marker.parent
        try:
            complete=json.loads(marker.read_text())
            if complete.get('status')!='complete':continue
            metadata=json.loads((folder/'metadata.json').read_text())
            # Use the current publication inventory, not stale image folders from older runs.
            exports.append({'path':str(folder),'run_uid':complete['run_uid'],'image_count':complete['image_count'],'cell_count':complete['cell_count']})
        except (OSError,ValueError,KeyError):continue
    return exports

def analyze(paths, max_distance=80, same_experiment=False):
    radius=float(max_distance)
    if not math.isfinite(radius) or not 0<radius<=500:raise ValueError('Matching distance must be between 0 and 500 pixels')
    if len(paths)<1:raise ValueError('Select at least one completed export')
    observations=[];groups={};seen=set();warnings=[];datasets=set();feature_names=None
    for folder in map(lambda x:Path(x).expanduser().resolve(),paths):
        completion=json.loads((folder/'COMPLETE.json').read_text())
        if completion.get('status')!='complete':raise ValueError('Export is not complete: '+str(folder))
        with (folder/'cells_all_images.csv').open() as h:
            reader=csv.DictReader(h);rows=list(reader)
            names={n for n in reader.fieldnames if n.startswith(('AreaShape_','Intensity_','Texture_','Neighbors_','Location_','Number_'))}
            feature_names=names if feature_names is None else feature_names & names
        if len(rows)!=completion['cell_count']:raise ValueError('Cell count does not match completion record')
        by_image={}
        for row in rows:by_image.setdefault(row['image_uid'],[]).append(row)
        # Published metadata contains the exact image list for this batch.
        inventory=json.loads((folder/'metadata.json').read_text())['images']
        for entry in inventory:
            # See publisher inventory structure; resolve only paths inside export.
            rel=entry['output_folder']
            p=(folder/rel/'metadata.json').resolve()
            if not p.is_relative_to(folder):raise ValueError('Invalid image metadata path')
            meta=json.loads(p.read_text());im=meta['image'];uid=im['image_uid']
            if uid in seen:raise ValueError('Duplicate image selected across exports: '+im['source_path'])
            seen.add(uid)
            ds=meta.get('readme_fields',{}).get('dataset_id')
            if ds:datasets.add(ds)
            stamp=im.get('acquisition_local_time')
            if not stamp:raise ValueError('Acquisition timestamp missing: '+im['source_path'])
            time=datetime.fromisoformat(stamp)
            key=(im.get('well_id'),im.get('field_id'))
            if not all(key):raise ValueError('Well or field missing: '+im['source_path'])
            registration=im.get('registration')
            if not registration:raise ValueError('Fiducial registration missing: '+im['source_path'])
            image_rows=by_image.pop(uid,[])
            if len(image_rows)!=meta['cell_count']:raise ValueError('Per-image cell count mismatch')
            groups.setdefault(key,[]).append(dict(image=im,rows=image_rows,time=time,folder=str(p.parent),export_path=str(folder)))
        if by_image:raise ValueError('Table contains images absent from publication inventory')
    if len(datasets)>1:
        if not same_experiment:raise ValueError('README dataset names differ. Confirm these exports belong to the same experiment.')
        warnings.append('Different README dataset names retained; operator confirmed the same experiment.')
    if not datasets:warnings.append('Dataset ID unavailable; experiment identity must be checked by the operator.')
    summaries=[];pairs=[];candidates=[]
    for (well,field),frames in sorted(groups.items()):
        frames.sort(key=lambda f:f['time'])
        if len({f['time'] for f in frames})!=len(frames):raise ValueError(f'Duplicate acquisition time in {well}/{field}')
        ref=frames[0]['image']['registration']
        for frame in frames:
            im=frame['image'];reg=im['registration']
            # Measurements already live in each export's reference coordinates.
            dx=ref['reference_center_x_px']-reg['reference_center_x_px'];dy=ref['reference_center_y_px']-reg['reference_center_y_px']
            cells=[]
            for r in frame['rows']:
                cell={'observation_uid':r['cell_uid'],'image_uid':im['image_uid'],'well_id':well,'field_id':field,'acquisition_local_time':im['acquisition_local_time'],'x_reference_px':float(r['AreaShape_Center_X'])+dx,'y_reference_px':float(r['AreaShape_Center_Y'])+dy,'translation_x_px':dx,'translation_y_px':dy,'track_uid':'','parent_track_uid':''}
                for feature in sorted(feature_names):cell[feature]=r.get(feature,'')
                observations.append(cell);cells.append(cell)
            frame['cells']=cells
            summary={'export_path':frame['export_path'],'well_id':well,'field_id':field,'image_uid':im['image_uid'],'source':im['source_path'],'time':im['acquisition_local_time'],'cell_count':len(cells),'translation_x_px':dx,'translation_y_px':dy,'folder':frame['folder']}
            for feature in FEATURES:
                values=sorted(float(c[feature]) for c in cells if c.get(feature,'')!='' and math.isfinite(float(c[feature])))
                n=len(values);summary[feature+'_median']=(values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2) if n else None
            summary.update(measure_coverage(frame['folder']))
            summaries.append(summary)
        for a,b in zip(frames,frames[1:]):
            hours=(b['time']-a['time']).total_seconds()/3600
            pairs.append({'well_id':well,'field_id':field,'from_time':a['time'].isoformat(),'to_time':b['time'].isoformat(),'elapsed_hours':hours,'from_count':len(a['cells']),'to_count':len(b['cells']),'count_change':len(b['cells'])-len(a['cells'])})
            # Spatial candidates only; no automatic identity or lineage assignment.
            edges=[]
            for ca in a['cells']:
                for cb in b['cells']:
                    d=math.hypot(ca['x_reference_px']-cb['x_reference_px'],ca['y_reference_px']-cb['y_reference_px'])
                    if d<=radius:edges.append((ca,cb,d))
            for ca,cb,d in edges:
                na=sum(x[0] is ca for x in edges);nb=sum(x[1] is cb for x in edges)
                candidates.append({'well_id':well,'field_id':field,'from_observation_uid':ca['observation_uid'],'to_observation_uid':cb['observation_uid'],'distance_px':d,'elapsed_hours':hours,'status':'unique_spatial_candidate' if na==nb==1 else 'ambiguous','review_status':'unreviewed'})
    unavailable=sum(i['coverage_status']!='available' for i in summaries)
    if unavailable:warnings.append(f'Cell coverage unavailable for {unavailable} images; see coverage_note in the image table. Missing masks are not treated as zero coverage.')
    warnings.append('Total cell area and coverage count occupied segmentation pixels inside each image’s valid region; they describe the imaged field, not the whole well or a common overlap across time.')
    warnings += ['Candidate links are not confirmed tracks, divisions, or death events.', 'Count tables and summary medians cover whole fields; the statistical plate filters cell centroids to the shared valid image area.', 'Alignment is translation-only and requires visual review; a single fiducial cannot establish rotation or scale.', 'Local timestamps retain their original timezone uncertainty. Distances are in pixels.']
    return {'feature_names':sorted(feature_names), 'exports':paths,'dataset_ids':sorted(datasets),'field_count':len(groups),'image_count':len(summaries),'observation_count':len(observations),'matching_radius_px':radius,'images':summaries,'intervals':pairs,'observations':observations,'candidates':candidates,'warnings':warnings}
