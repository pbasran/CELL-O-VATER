"""Versioned import profiles, applied without guessing vendor conventions."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]


def load_profiles(override=None):
    from jsonschema import Draft202012Validator
    schema = json.loads((BASE/'schema/imaging_profile.schema.json').read_text())
    profiles = {}
    for path in [BASE/'profiles/existing_system.json', BASE/'profiles/celloger.json'] + ([Path(override)] if override else []):
        value = json.loads(path.read_text())
        Draft202012Validator(schema).validate(value)
        pattern = value['grouping']['filename_pattern']
        if pattern:
            compiled = re.compile(pattern)
            if not {'sequence','frame'}.issubset(compiled.groupindex):
                raise ValueError('Filename pattern requires named sequence and frame groups')
        for rule in value['detection_rules']:
            re.compile(rule['pattern'])
        profiles[value['imaging_source']] = value
    return profiles


def lookup(obj, path):
    for key in path:
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def detect_profile(image, raw, profiles):
    matches = []
    for name, profile in profiles.items():
        for rule in profile['detection_rules']:
            value = image['imaging_metadata'].get(rule['field']) if rule['field'] != 'tiff_software' else raw['embedded'].get('tiff_software')
            if value and re.search(rule['pattern'], str(value), re.I):
                matches.append(name)
                break
    return matches


def apply_profiles(manifest, raw_records, profiles, requested):
    from .importer import identity, record
    manifest['profile_snapshots'] = profiles
    manifest['profile_configuration_sha256'] = hashlib.sha256(json.dumps(profiles,sort_keys=True).encode()).hexdigest()
    groups = {}
    detected_sources = set()
    for original in manifest['images']:
        image = original
        # Copies keep per-frame profile state independent.
        image['warnings'] = list(image['warnings'])
        image['imaging_metadata'] = dict(image['imaging_metadata'])
        image['imaging_metadata_provenance'] = copy.deepcopy(image['imaging_metadata_provenance'])
        image['metadata_conflicts'] = list(image['metadata_conflicts'])
        raw = raw_records[image['raw_metadata_record_index']]
        matches = detect_profile(image,raw,profiles)
        selected = requested if requested != 'auto' else matches[0] if len(matches)==1 else None
        image['detected_imaging_sources'] = matches
        detected_sources.update(matches)
        image['configuration_issues'] = []
        if selected is None:
            image['configuration_issues'].append('Select an imaging profile; detection is absent or ambiguous.')
            image['imaging_source'] = 'unknown'
            continue
        p = profiles[selected]
        image['imaging_source'] = selected
        image['profile_id'] = p['profile_id']
        image['profile_selection_source'] = 'user_supplied' if requested!='auto' else 'metadata'
        issues = image['configuration_issues']
        if matches and matches != [selected]:
            issues.append('Selected imaging profile conflicts with metadata evidence.')
        if p['validation_status'] != 'validated_on_representative_exports':
            issues.append('Profile has not been validated on representative device exports.')
        # Explicit profile mappings are needed for vendor keys. Canonical fields stay intact on conflict.
        meta = {'values':image['imaging_metadata'],'provenance':image['imaging_metadata_provenance'],
                'conflicts':image['metadata_conflicts']}
        for rule in p['metadata_mappings']:
            candidates = []
            if rule['source'] == 'sidecar_json':
                for sidecar in raw['sidecars']:
                    if sidecar['path'].lower().endswith('.json'):
                        candidates.append((json.loads(sidecar['raw']),sidecar['path'],'sidecar_metadata'))
            elif rule['source'] == 'tiff_description_json':
                try:
                    candidates.append((json.loads(raw['embedded'].get('tiff_image_description') or '{}'),image['image_relative_path'],'embedded_metadata'))
                except ValueError:
                    image['warnings'].append('TIFF description is not JSON; configured mapping unavailable.')
            for data, reference, source in candidates:
                value=lookup(data,rule['path'])
                if isinstance(value,(str,int,float)) and not isinstance(value,bool):
                    record(meta,rule['field'],value,source,reference,'.'.join(rule['path']))
        if image['metadata_conflicts']:
            issues.append('Resolve metadata conflicts before analysis.')
        calibrated = {}; provenance = {}
        for axis in 'xyz':
            item=image['acquisition'].get('physical_sampling',{}).get(axis)
            value=None
            if item:
                factor={'µm':1,'um':1,'μm':1,'nm':.001,'mm':1000,'m':1_000_000}.get(item['unit'])
                try:
                    value=float(item['value'])*factor if factor is not None else None
                except (TypeError,ValueError):pass
                if value is not None and (not math.isfinite(value) or value<=0):value=None
                if value is None:issues.append(f'Unsupported or invalid {axis} calibration metadata.')
            fallback=p['calibration_um'][axis]
            calibrated[axis]=value if value is not None else fallback
            provenance[axis]='embedded_metadata' if value is not None else 'user_supplied_profile' if fallback is not None else 'unknown'
        image['pixel_size_um']=calibrated;image['calibration_source']=provenance
        if calibrated['x'] is None or calibrated['y'] is None:
            issues.append('Pixel calibration is missing; physical-unit measurements unavailable.')
        channels=image['acquisition'].get('channels',[])
        channel_axis='C' if 'C' in image['axes'] else 'S' if 'S' in image['axes'] else None
        count=image['shape'][image['axes'].index(channel_axis)] if channel_axis else 1
        selector=p['channels']['segmentation']
        index=None
        if isinstance(selector,int) and selector<count:index=selector
        if isinstance(selector,str):
            found=[i for i,c in enumerate(channels) if c.get('name')==selector]
            if len(found)==1:index=found[0]
        image['segmentation_channel_index']=index
        if index is None:issues.append('Select a valid, unambiguous segmentation channel.')
        image['measurement_channel_selection']=p['channels']['measurement']
        for measurement in p['channels']['measurement']:
            valid=(isinstance(measurement,int) and measurement<count) or (isinstance(measurement,str) and sum(c.get('name')==measurement for c in channels)==1)
            if not valid:issues.append(f'Measurement channel not found: {measurement}')
        image['analysis_defaults']=p['analysis_defaults']
        image['elapsed_time_s']=None
        time=image['acquisition'].get('frame_times',{}).get(str(image['frame_index']))
        if time:
            factor={'s':1,'ms':.001,'µs':.000001,'min':60,'h':3600}.get(time['unit'])
            try:
                seconds=float(time['value'])*factor if factor is not None else None
                if seconds is not None and math.isfinite(seconds) and seconds>=0:
                    image['elapsed_time_s']=seconds
            except (TypeError,ValueError):pass
        image['elapsed_time_source']='embedded_metadata' if image['elapsed_time_s'] is not None else 'unknown'
        source_frame=image['frame_index']
        sequence=image['sequence_uid'];frame=source_frame;channel='embedded'
        pattern=p['grouping']['filename_pattern']
        if pattern:
            match=re.fullmatch(pattern,image['image_relative_path'])
            if not match:
                issues.append('Filename does not match profile grouping pattern.')
            elif 'T' in image['axes'] and image['shape'][image['axes'].index('T')]>1:
                issues.append('Filename grouping cannot be combined with an embedded time series.')
            else:
                parts=match.groupdict()
                try:
                    frame=int(parts['frame'])-p['grouping']['frame_index_base']
                    if frame<0:raise ValueError()
                    channel=parts.get('channel') or 'embedded'
                    sequence=identity(manifest['dataset_uid']+':profile-sequence:'+parts['sequence']+':series:'+str(image['series_index']))
                    image['grouping_status']='profile_filename_pattern'
                except ValueError:
                    issues.append('Filename frame number is invalid for the configured index base.')
                    frame=source_frame
        else:
            image['warnings'].append('Files remain separate sequences until a filename grouping rule is configured.')
        if image['elapsed_time_s'] is None and p['timing']['frame_interval_s'] is not None:
            image['elapsed_time_s']=frame*p['timing']['frame_interval_s']
            image['elapsed_time_source']='user_supplied_profile'
        image['source_frame_index']=source_frame
        image['sequence_uid']=sequence;image['frame_index']=frame
        key=(sequence,frame)
        group=groups.setdefault(key,{'sequence_uid':sequence,'frame_index':frame,'members':[], 'issues':[], 'expected_file_channels':p['grouping']['expected_file_channels'], 'segmentation_file_channel':p['channels']['segmentation_file_channel']})
        if any(m['channel']==channel for m in group['members']):group['issues'].append('Duplicate input for this sequence/frame/channel.')
        group['members'].append({'source_image_uid':image['image_uid'],'channel':channel,'path':image['image_relative_path'], 'spatial_shape':{axis:image['shape'][image['axes'].index(axis)] for axis in 'XYZ' if axis in image['axes']}, 'pixel_size_um':calibrated})
        group['issues'].extend(issues)
    manifest['logical_images']=[]
    for (sequence,frame),group in sorted(groups.items()):
        members=sorted(group['members'],key=lambda x:(x['channel'],x['path']))
        group['members']=members
        if len({json.dumps(m['spatial_shape'],sort_keys=True) for m in members})>1:
            group['issues'].append('Channel files have incompatible spatial dimensions.')
        if len({json.dumps(m['pixel_size_um'],sort_keys=True) for m in members})>1:
            group['issues'].append('Channel files have incompatible pixel calibration.')
        selector=group['segmentation_file_channel']
        selected_members=[m for m in members if m['channel']==selector] if selector else members if len(members)==1 else []
        group['segmentation_source_image_uid']=selected_members[0]['source_image_uid'] if len(selected_members)==1 else None
        if group['segmentation_source_image_uid'] is None:
            group['issues'].append('Select exactly one filename channel for segmentation.')
        expected=group['expected_file_channels']
        if len(members)>1 and not expected:
            group['issues'].append('Specify expected filename channels to check frame completeness.')
        if expected and set(expected)!={m['channel'] for m in members}:
            group['issues'].append('Missing or unexpected channel files for this frame.')
        group['image_uid']=identity(sequence+':'+str(frame)+':'+':'.join(m['source_image_uid'] for m in members))
        group['issues']=sorted(set(group['issues']))
        group['profile_checks_passed']=not group['issues']
        manifest['logical_images'].append(group)
    manifest['detected_profile']=next(iter(detected_sources)) if len(detected_sources)==1 else 'unknown'
    manifest['selected_profile']=requested if requested!='auto' else manifest['detected_profile']
    manifest['profile_selection_source']='user_supplied' if requested!='auto' else 'metadata' if detected_sources else 'unknown'
    manifest['profile_readiness_scope']='Import profile checks only; segmentation and measurement pipelines are not implemented or validated.'
    manifest['configuration_summary']={'input_frames':len(manifest['images']),'logical_images':len(groups),
        'logical_images_passing_profile_checks':sum(g['profile_checks_passed'] for g in manifest['logical_images']),
        'unassigned_input_frames':sum(i['imaging_source']=='unknown' for i in manifest['images'])}
