"""Cellpose run preparation and safe, explicit 2D image-plane selection."""
import hashlib
import json
import math
from pathlib import Path
import uuid

from .profiles import BASE
from .importer import digest

PYTHON = BASE/'.venv-cellpose/bin/python'
SAM_PYTHON = BASE/'.venv-cellpose-sam/bin/python'
MODELS = BASE/'models'


def validate_options(options):
    if not isinstance(options,dict):raise ValueError('Segmentation settings must be an object')
    if options.get('model') not in {'cyto3','nuclei','cpsam_v2'}:raise ValueError('Select Cellpose-SAM, cyto3 or nuclei')
    result={'model':options['model']}
    register=options.get('register_fiducial',False)
    if not isinstance(register,bool):raise ValueError('register_fiducial must be true or false')
    result['register_fiducial']=register
    exclude=options.get('exclude_black_border',False)
    if not isinstance(exclude,bool):raise ValueError('exclude_black_border must be true or false')
    result['exclude_black_border']=exclude
    for key,default,minimum in [('channel',0,0),('z_plane',0,0),('min_size',15,1),('image_limit',0,0)]:
        value=options.get(key,default)
        if isinstance(value,bool) or not isinstance(value,int) or value<minimum:raise ValueError(f'{key} must be an integer ≥ {minimum}')
        result[key]=value
    for key,default,maximum in [('tile_norm_blocksize',0,2048),('niter',0,5000)]:
        value=options.get(key,default)
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=maximum:raise ValueError(f'{key} must be an integer from 0 to {maximum}')
        if key=='tile_norm_blocksize' and 0<value<32:raise ValueError('Local contrast window must be 0 or at least 32 pixels')
        result[key]=value
    for key,default,lower,upper in [('diameter',0 if options['model']=='cpsam_v2' else 30,0 if options['model']=='cpsam_v2' else 1,1000),('flow_threshold',.4,0,5),('cellprob_threshold',0,-10,10)]:
        value=options.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lower<=value<=upper:raise ValueError(f'{key} must be between {lower} and {upper}')
        result[key]=value
    return result


def read_plane(root,image,channel,z_plane):
    """Select T/C/Z explicitly. Reject unknown non-singleton axes rather than guessing."""
    import numpy as np
    from PIL import Image
    root=Path(root).resolve()
    path=(root/image['image_relative_path']).resolve()
    if not path.is_relative_to(root):raise ValueError('Image is outside the dataset folder')
    frame=image.get('source_frame_index',image['frame_index'])
    selectors={'T':frame,'C':channel,'S':channel,'Z':z_plane}
    if path.suffix.lower() in {'.tif','.tiff'}:
        import tifffile
        with tifffile.TiffFile(path) as tif:
            series=tif.series[image['series_index']]
            axes=series.axes
            if 'C' in axes and 'S' in axes:raise ValueError('Combined C and S axes require an explicit channel mapping')
            for axis,index in [('C',channel),('Z',z_plane),('T',frame)]:
                actual='S' if axis=='C' and 'S' in axes else axis
                if actual not in axes and index!=0:raise ValueError(f'{axis} index {index} is outside this image')
            first=series.pages[0]
            page_axes=first.axes
            if not axes.endswith(page_axes):raise ValueError('Unsupported TIFF axis layout')
            leading=axes[:-len(page_axes)]
            page_number=0
            for axis,size in zip(leading,series.shape):
                index=selectors.get(axis,0)
                if axis not in selectors and size!=1:raise ValueError(f'Unspecified stack axis {axis}; configure the image format first')
                if not 0<=index<size:raise ValueError(f'{axis} index {index} is outside this image')
                page_number=page_number*size+index
            page=series.pages[page_number]
            if math.prod(page.shape)>64_000_000:raise ValueError('Selected TIFF page exceeds the current 64-million-sample limit')
            data=page.asarray()
        selection=[];remaining=[]
        for axis,size in zip(page_axes,data.shape):
            if axis in 'YX':selection.append(slice(None));remaining.append(axis)
            else:
                if axis not in selectors and size!=1:raise ValueError(f'Unsupported axis {axis}')
                index=selectors.get(axis,0)
                if not 0<=index<size:raise ValueError(f'{axis} index {index} is outside this image')
                selection.append(index)
        data=data[tuple(selection)]
        if remaining==['X','Y']:data=data.T
        elif remaining!=['Y','X']:raise ValueError('Selected plane must have X and Y dimensions')
    else:
        if z_plane or frame:raise ValueError('This image has no requested Z plane or frame')
        with Image.open(path) as image_file:
            if image_file.width*image_file.height>20_000_000:raise ValueError('Image exceeds current 20-million-pixel limit')
            if image_file.mode=='P':image_file=image_file.convert('RGB')
            data=np.asarray(image_file)
        if data.ndim==3:
            if channel>=data.shape[-1]:raise ValueError('Channel index is outside this image')
            data=data[:,:,channel]
        elif channel:raise ValueError('This image has only channel 0')
    if data.ndim!=2 or min(data.shape)<8:raise ValueError('Segmentation requires a 2D plane at least 8 × 8 pixels')
    if not np.isfinite(data).all():raise ValueError('Image contains non-finite pixel values')
    return np.asarray(data,dtype=np.float32)


def make_plan(manifest,options):
    options=validate_options(options)
    if options['register_fiducial'] and not manifest.get('series_summary'):
        raise ValueError('Registration could not start: image grouping failed before fiducial detection. Expected a well/field filename such as A2_0000.tiff or A2_0000-1.tiff, plus an acquisition timestamp. '+manifest.get('registration_grouping_error',''))
    images={i['image_uid']:i for i in manifest['images']}
    groups=list(manifest.get('logical_images',[]))
    assigned={m['source_image_uid'] for g in groups for m in g['members']}
    # Unknown instruments can still be segmented as independent images.
    for uid,image in images.items():
        if uid not in assigned:groups.append({'image_uid':uid,'members':[{'source_image_uid':uid}], 'issues':[], 'segmentation_source_image_uid':uid})
    if not groups:raise ValueError('No readable images are available')
    fatal=('Duplicate input','incompatible','Missing or unexpected channel','Filename does not match','Filename frame number is invalid','Filename grouping cannot','Selected imaging profile conflicts')
    plan=[]
    for group in groups:
        problems=[p for p in group.get('issues',[]) if any(word in p for word in fatal)]
        if problems:raise ValueError('Resolve import grouping errors first: '+'; '.join(problems))
        uid=group.get('segmentation_source_image_uid')
        if uid is None:
            if len(group['members'])!=1:raise ValueError('Select a filename channel for segmentation in the imaging profile')
            uid=group['members'][0]['source_image_uid']
        source=images[uid]
        plan.append({'image_uid':group['image_uid'],'source':source})
    plan.sort(key=lambda item:(item['source'].get('well_id',''),item['source'].get('field_id',''),item['source']['frame_index'],item['source']['image_relative_path']))
    if options['image_limit']:plan=plan[:options['image_limit']]
    return options,plan


def prepare_run(manifest,options,destination,progress=lambda **kw:None):
    import numpy as np
    options,plan=make_plan(manifest,options)
    destination=Path(destination)
    (destination/'inputs').mkdir(parents=True)
    expected={f['path']:f.get('sha256') for f in manifest['files']}
    checked=set();spec={'run_uid':str(uuid.uuid4()),'options':options,'frames':[],
        'dataset_uid':manifest['dataset_uid'],'dataset_root':manifest['dataset_root'],
        'profile_configuration_sha256':manifest.get('profile_configuration_sha256'),
        'model_directory':str(MODELS),'output_directory':str(destination)}
    for index,item in enumerate(plan):
        source=item['source'];name=source['image_relative_path']
        read_root=manifest.get('_local_dataset_root',manifest['dataset_root'])
        path=Path(read_root)/name
        if name not in checked:
            if not expected.get(name) or digest(path)!=expected[name]:raise ValueError(f'Image changed since import: {name}. Import the dataset again.')
            checked.add(name)
        progress(stage='preparing',completed=index,total=len(plan),message=f'Reading {name}')
        plane=read_plane(read_root,source,options['channel'],options['z_plane'])
        filename=f'inputs/{index:06d}.npy'
        np.save(destination/filename,plane,allow_pickle=False)
        spec['frames'].append({'image_uid':item['image_uid'],'source_image_uid':source['image_uid'],
            'source_path':name,'source_sha256':expected[name], 'series_index':source['series_index'],
            'source_frame_index':source.get('source_frame_index',source['frame_index']),
            'frame_index':source['frame_index'],'sequence_uid':source['sequence_uid'],
            'well_id':source.get('well_id'),'field_id':source.get('field_id'),
            'reference_source_image_uid':source.get('reference_source_image_uid'),
            'acquired_at':source.get('acquired_at'),'acquisition_local_time':source.get('acquisition_local_time'),
            'input_relative_path':filename,'shape':list(plane.shape)})
    (destination/'import_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'job_spec.json').write_text(json.dumps(spec,indent=2)+'\n')
    return spec
