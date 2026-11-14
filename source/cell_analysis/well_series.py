"""Group fields by well and field suffix, with acquisition time from image metadata."""
from datetime import datetime
import re


def group_well_series(manifest):
    from .importer import identity
    series={}
    for image in manifest['images']:
        match=re.fullmatch(r'(?:.*/)?(?P<well>[A-F][1-8])_(?P<field>\d+)(?:-\d+)?\.(?:tiff?|jpe?g)',image['image_relative_path'],re.I)
        if not match:raise ValueError('Cannot identify well and field from '+image['image_relative_path'])
        well=match['well'].upper();field=match['field']
        stamp=image['acquisition'].get('acquisition_local_time')
        if not stamp:raise ValueError('Acquisition time missing for '+image['image_relative_path'])
        # Dates establish order only; timezone-free JPEG timestamps are not converted to UTC.
        order=datetime.fromisoformat(stamp)
        series.setdefault((well,field),[]).append((order,image))
    for (well,field),members in series.items():
        if len({stamp for stamp,_ in members})!=len(members):raise ValueError(f'Duplicate acquisition time in well {well}, field {field}')
    logical=[]
    for (well,field),members in sorted(series.items()):
        members.sort(key=lambda x:x[0])
        if len({stamp for stamp,_ in members})!=len(members):raise ValueError(f'Duplicate acquisition time in well {well}, field {field}')
        sequence=identity(manifest['dataset_uid']+':well:'+well+':field:'+field)
        reference=members[0][1]['image_uid']
        for index,(_,image) in enumerate(members):
            image.update(well_id=well,field_id=field,sampling_scope='field_within_well',acquisition_local_time=image['acquisition']['acquisition_local_time'])
            image['warnings']=[w for w in image.get('warnings',[]) if w!='Files remain separate sequences until a filename grouping rule is configured.']
            image['source_frame_index']=image.get('source_frame_index',image['frame_index'])
            image.update(sequence_uid=sequence,frame_index=index,grouping_status='well_field_acquisition_time',reference_source_image_uid=reference)
            logical.append({'image_uid':image['image_uid'],'sequence_uid':sequence,'frame_index':index,
                'well_id':well,'field_id':field,'reference_source_image_uid':reference,
                'members':[{'source_image_uid':image['image_uid'],'channel':'embedded','path':image['image_relative_path']}],
                'segmentation_source_image_uid':image['image_uid'],'issues':image.get('configuration_issues',[]),
                'profile_checks_passed':False})
    manifest['logical_images']=logical
    manifest['series_summary']={'well_count':len({k[0] for k in series}),'field_series_count':len(series),'acquisitions_per_series':sorted(set(len(v) for v in series.values())),
        'time_order':'Image acquisition local time; timezone-less timestamps retained as local time, not UTC.',
        'sampling_scope':'Each image covers one field within its well, not the entire well.'}
    manifest['configuration_summary']['logical_images']=len(logical)
    return manifest
