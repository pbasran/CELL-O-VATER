"""Publish a complete run together; downstream consumers wait for COMPLETE.json."""
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import shutil
import uuid


def output_root(dataset, requested=None):
    from .mirrored_outputs import layout
    return Path(layout(dataset,requested)['processed_root'])


def publish_run(segmentation, measurements, target, dataset_root, trial_masks=None):
    """Publish mirrored results; preserve the historical preview export path."""
    if trial_masks is None:
        from .mirrored_outputs import publish
        return publish(segmentation,measurements,target,dataset_root)
    segmentation=Path(segmentation);measurements=Path(measurements) if measurements else None
    if not measurements or json.loads((measurements/'summary.json').read_text()).get('status')!='complete':
        raise ValueError('Measurements must finish before a run can be published')
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    staging=target/('.'+name+'.partial');destination=target/name;staging.mkdir()
    try:
        manifest=json.loads((segmentation/'segmentation_manifest.json').read_text())
        if trial_masks is None:
            for directory in ('masks','overlays','registered_images','analysis_regions'):
                if (segmentation/directory).exists():shutil.copytree(segmentation/directory,staging/directory)
        else:
            # The accepted preview has SAM masks alongside an older reference run.
            trial=Path(trial_masks);(staging/'masks').mkdir();(staging/'overlays').mkdir()
            summary=json.loads((measurements/'summary.json').read_text())
            manifest['model']='cpsam_v2';manifest['object_count']=summary['cell_count']
            manifest['run_uid']=summary['segmentation_run_uid'];manifest['measurement_status']='complete'
            experiment=json.loads((trial/'experiment.json').read_text())
            manifest['model_sha256']=experiment['model_sha256']
            manifest['options']=experiment['options']
            manifest['engine_version']=experiment['version']
            manifest['device']=experiment['device']
            checks=json.loads((trial/'results.json').read_text())
            manifest.pop('torch_version',None)
            manifest.pop('started_at',None)
            manifest['completed_at']=summary['completed_at']
            for i,image in enumerate(manifest['images']):
                shutil.copy2(trial/f'{i}-labels.tif',staging/f'masks/{i:06d}_labels.tif')
                shutil.copy2(trial/f'{i}-overlay.png',staging/f'overlays/{i:06d}.png')
                image['excluded_object_count']=checks[i]['excluded_objects']
                image['overlay_display_bounds']=checks[i]['display_bounds']
                image.update(mask_relative_path=f'masks/{i:06d}_labels.tif',overlay_relative_path=f'overlays/{i:06d}.png',object_count=summary['per_image_counts'][i])
            for directory in ('registered_images','analysis_regions'):
                shutil.copytree(segmentation/directory,staging/directory)
            shutil.copy2(trial/'experiment.json',staging/'sam-experiment.json')
        for name in ('cells.csv','cells.json','summary.json','provenance.json','measurements.cppipe','identity-map.json'):
            shutil.copy2(measurements/name,staging/name)
        if (measurements/'inputs').exists():
            shutil.copytree(measurements/'inputs',staging/'measurement_inputs')
            csv_text=(measurements/'inputs.csv').read_text().replace(str(measurements/'inputs'),str(destination/'measurement_inputs'))
            (staging/'inputs.csv').write_text(csv_text)
            pipeline=(staging/'measurements.cppipe').read_text().replace(str(measurements),str(destination))
            (staging/'measurements.cppipe').write_text(pipeline)
            provenance=json.loads((staging/'provenance.json').read_text())
            provenance['published_pipeline_sha256']=hashlib.sha256((staging/'measurements.cppipe').read_bytes()).hexdigest()
            provenance['published_pipeline_note']='Input paths updated for this published folder; original pipeline_sha256 identifies the executed pipeline.'
            (staging/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        if (segmentation/'import_manifest.json').exists():shutil.copy2(segmentation/'import_manifest.json',staging/'import_manifest.json')
        manifest['published_directory']=str(destination)
        (staging/'segmentation_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        complete={'status':'complete','source_folder':str(dataset_root),'output_directory':str(destination),'completed_at':datetime.now(timezone.utc).isoformat(),'cell_count':json.loads((measurements/'summary.json').read_text())['cell_count'],'table':'cells.csv','table_json':'cells.json','segmentation_manifest':'segmentation_manifest.json','mask_labels':'Original SAM mask labels; cp_object_number is a separate measurement label.'}
        (staging/'COMPLETE.json').write_text(json.dumps(complete,indent=2)+'\n')
        staging.rename(destination)
        return str(destination)
    except Exception:
        # Leave partial work clearly marked for diagnosis; never expose it as complete.
        raise


def required_working_bytes(plan):
    """Conservative staging + measurement + published-copy budget, including headroom."""
    pixels=0
    for item in plan:
        image=item['source'];axes=image['axes'];shape=image['shape']
        pixels+=shape[axes.index('Y')]*shape[axes.index('X')]
    return pixels*36+5*1024**3

def check_working_space(plan,working,destination):
    required=required_working_bytes(plan)
    for directory in (Path(working),Path(destination)):
        free=shutil.disk_usage(directory).free
        if free<required:
            raise ValueError(f'Not enough free disk space for this batch. Allow about {required/1024**3:.0f} GB free; {free/1024**3:.0f} GB available at {directory}. Free space or choose a smaller image limit before running.')
    return required
