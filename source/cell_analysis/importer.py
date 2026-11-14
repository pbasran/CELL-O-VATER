"""Read-only dataset inventory. Run with python -m cell_analysis.importer PATH --output DIR."""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

VERSION = '0.2.0'
SUPPORTED = {'.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp'}
PROPRIETARY = {'.nd2', '.czi', '.lif', '.vsi', '.ims'}
FIELDS = ['imaging_device_name', 'imaging_device_manufacturer', 'imaging_device_model',
          'imaging_device_serial_number', 'imaging_device_hardware_revision',
          'imaging_device_firmware_version', 'acquisition_software_name',
          'acquisition_software_version', 'acquisition_software_build',
          'camera_manufacturer', 'camera_model', 'camera_serial_number', 'objective_model']
NS = uuid.UUID('836f9017-ce61-4d4c-b8c1-df0421095dc1')

def identity(text):
    return str(uuid.uuid5(NS, text))

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def empty_metadata():
    return {'values': dict.fromkeys(FIELDS), 'provenance': {
        k: {'source': 'unknown', 'source_reference': None, 'metadata_key': None, 'raw_value': None}
        for k in FIELDS}, 'conflicts': [], 'warnings': []}

def record(meta, key, value, source, reference, original_key):
    if value is None or str(value).strip() == '':
        return
    value = str(value).strip()
    evidence = dict(source=source, source_reference=reference, metadata_key=original_key, raw_value=value)
    if meta['values'][key] is not None and meta['values'][key] != value:
        meta['conflicts'].append({'field': key, 'retained_value': meta['values'][key],
                                  'alternative_value': value, 'alternative_provenance': evidence})
    else:
        meta['values'][key] = value
        meta['provenance'][key] = evidence

def local_name(tag):
    return tag.rsplit('}', 1)[-1]

def ome_metadata(xml, series_index, meta, reference):
    """Use linked OME instrument metadata; never copy another instrument's fields."""
    root = ET.fromstring(xml)
    images = [e for e in root if local_name(e.tag) == 'Image']
    if series_index >= len(images):
        meta['warnings'].append('OME image-to-series mapping unavailable.')
        return {}
    im = images[series_index]
    pixels = next((e for e in im if local_name(e.tag) == 'Pixels'), None)
    ref = next((e.get('ID') for e in im if local_name(e.tag) == 'InstrumentRef'), None)
    instrument = next((e for e in root if local_name(e.tag) == 'Instrument' and e.get('ID') == ref), None)
    if instrument is not None:
        for tag, mapping in [('Microscope', {'Manufacturer':'imaging_device_manufacturer','Model':'imaging_device_model','SerialNumber':'imaging_device_serial_number'})]:
            elements = [e for e in instrument if local_name(e.tag) == tag]
            if len(elements) == 1:
                for attr, key in mapping.items():
                    record(meta, key, elements[0].get(attr), 'embedded_metadata', reference, f'OME/Instrument[{ref}]/{tag}/@{attr}')
        for tag, mapping in [('Detector', {'Manufacturer':'camera_manufacturer','Model':'camera_model','SerialNumber':'camera_serial_number'}), ('Objective', {'Model':'objective_model'})]:
            elements = [e for e in instrument if local_name(e.tag) == tag]
            if len(elements) == 1:
                for attr,key in mapping.items():
                    record(meta,key,elements[0].get(attr),'embedded_metadata',reference,f'OME/Instrument[{ref}]/{tag}/@{attr}')
            elif len(elements) > 1:
                meta['warnings'].append(f'Multiple {tag} entries: component mapping requires profile configuration.')
    info = {'channels': [], 'physical_sampling': {}, 'frame_times': {}}
    acquisition = next((e.text for e in im if local_name(e.tag) == 'AcquisitionDate'), None)
    if acquisition:
        try:
            parsed = datetime.fromisoformat(acquisition.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                meta['warnings'].append('AcquisitionDate has no timezone; raw value retained, normalized timestamp unavailable.')
            else:
                info['acquired_at_frame_zero'] = parsed.isoformat()
        except ValueError:
            meta['warnings'].append('Invalid AcquisitionDate; raw value retained.')
    if pixels is not None:
        info['channels'] = [{'id': e.get('ID'), 'name': e.get('Name')} for e in pixels if local_name(e.tag) == 'Channel']
        for axis in 'XYZ':
            if pixels.get('PhysicalSize'+axis):
                info['physical_sampling'][axis.lower()] = {'value': pixels.get('PhysicalSize'+axis), 'unit': pixels.get('PhysicalSize'+axis+'Unit', 'µm')}
        times = {}
        for e in pixels:
            if local_name(e.tag) == 'Plane' and e.get('DeltaT') is not None:
                times.setdefault(e.get('TheT','0'), set()).add((e.get('DeltaT'),e.get('DeltaTUnit','s')))
        for frame, values in times.items():
            if len(values) == 1:
                value, unit = next(iter(values)); info['frame_times'][frame] = {'value':value,'unit':unit}
            else:
                meta['warnings'].append(f'Frame {frame} contains different plane/channel times; no single timestamp assigned.')
    return info

def apply_sidecar(path, meta, root):
    """Only explicit canonical field names are mapped until vendor profiles are available."""
    if path.stat().st_size > 8_000_000:
        raise ValueError('Sidecar exceeds 8 MB metadata limit')
    raw = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.json':
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError('Sidecar JSON must be an object')
        values = obj.get('imaging_metadata', obj)
        if not isinstance(values, dict):
            raise ValueError('imaging_metadata must be an object')
    else:
        tree = ET.fromstring(raw)
        values = {local_name(e.tag): e.text for e in tree.iter() if local_name(e.tag) in FIELDS}
    for key in FIELDS:
        if key in values and isinstance(values[key], (str, int, float)):
            record(meta, key, values[key], 'sidecar_metadata', str(path.relative_to(root)), key)
    return raw

def inspect_image(path, root):
    import logging
    import threading
    messages=[]
    owner=threading.get_ident()
    class Capture(logging.Handler):
        def emit(self, entry):
            if entry.thread==owner:messages.append(entry.getMessage())
    logger=logging.getLogger('tifffile');handler=Capture(level=logging.WARNING)
    logger.addHandler(handler)
    try:results=_inspect_image(path,root)
    finally:logger.removeHandler(handler)
    for result in results:
        result['metadata']['warnings'].extend('TIFF metadata reader: '+m for m in dict.fromkeys(messages))
    return results


def _inspect_image(path, root):
    relative = path.relative_to(root).as_posix()
    results = []
    if path.suffix.lower() in {'.tif', '.tiff'}:
        import tifffile
        with tifffile.TiffFile(path) as tif:
            ome = tif.ome_metadata
            for index, series in enumerate(tif.series):
                meta = empty_metadata()
                first = series.pages[0]
                # TIFF Software is a free-form string, not a reliably separable version.
                tag = first.tags.get('Software')
                if tag:
                    meta['warnings'].append('TIFF Software may identify export software rather than original acquisition software; verify profile mapping.')
                details = ome_metadata(ome, index, meta, relative) if ome else {}
                raw = {'ome_xml': ome, 'tiff_image_description': first.description,
                       'tiff_software': str(tag.value) if tag else None}
                from .echo_metadata import extract_echo
                echo_details,echo_raw=extract_echo(first,meta,relative)
                details.update(echo_details);raw.update(echo_raw)
                axes = series.axes
                shape = list(series.shape)
                if 'Q' in axes or 'I' in axes:
                    meta['warnings'].append('Unspecified stack axis; time ordering requires profile configuration.')
                results.append(dict(series_index=index, axes=axes, shape=shape,
                                    dtype=str(series.dtype), frame_count=shape[axes.index('T')] if 'T' in axes else 1,
                                    metadata=meta, acquisition=details, raw_metadata=raw))
    else:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            if getattr(im, 'n_frames', 1) != 1:
                raise ValueError('Animated/multipage non-TIFF images require an explicit import profile')
            meta=empty_metadata();acquisition={}
            exif=im.getexif();nested=exif.get_ifd(34665) if 34665 in exif else {}
            all_exif={**dict(exif),**nested}
            for tag,key in [(271,'camera_manufacturer'),(272,'camera_model'),(42033,'camera_serial_number')]:
                record(meta,key,all_exif.get(tag),'embedded_metadata',relative,f'EXIF/{tag}')
            timestamp=all_exif.get(36867);offset=all_exif.get(36881)
            if timestamp and offset:
                try:acquisition['acquired_at_frame_zero']=datetime.strptime(str(timestamp).strip('\x00')+str(offset).strip('\x00'),'%Y:%m:%d %H:%M:%S%z').isoformat()
                except ValueError:meta['warnings'].append('Invalid EXIF acquisition timestamp; original value retained.')
            elif timestamp:meta['warnings'].append('EXIF acquisition time has no timezone; original value retained.')
            from types import SimpleNamespace
            from PIL import ExifTags
            from .echo_metadata import extract_echo
            echo_tags={305:SimpleNamespace(value=all_exif.get(305,'')),34665:SimpleNamespace(value={ExifTags.TAGS.get(k,str(k)):v for k,v in all_exif.items()})}
            if im.info.get('xmp'):echo_tags[700]=SimpleNamespace(value=im.info['xmp'])
            echo_details,echo_raw=extract_echo(SimpleNamespace(tags=echo_tags),meta,relative)
            acquisition.update(echo_details)
            axes='YXS' if len(im.getbands())>1 else 'YX'
            shape=[im.height,im.width]+([len(im.getbands())] if len(im.getbands())>1 else [])
            results.append(dict(series_index=0, axes=axes, shape=shape, dtype=im.mode,
                                frame_count=1,metadata=meta,acquisition=acquisition,
                                raw_metadata={'image_info': {str(k):str(v) for k,v in im.info.items()},
                                              'exif':{str(k):str(v) for k,v in all_exif.items()},'echo':echo_raw}))
    for result in results:
        # Match only exact basename companions, never unrelated folder-wide metadata.
        companions = sorted({p for p in [path.with_suffix('.json'), path.with_suffix('.xml'),
                                          Path(str(path)+'.json'),Path(str(path)+'.xml')] if p.is_file() and not p.is_symlink()})
        result['sidecars'] = []
        for p in companions:
            try:
                raw = apply_sidecar(p,result['metadata'],root)
                result['sidecars'].append({'path':p.relative_to(root).as_posix(),'sha256':digest(p),'raw':raw})
            except (OSError, ValueError, ET.ParseError) as exc:
                result['metadata']['warnings'].append(f'Sidecar {p.name}: {exc}')
    return results

def scan_dataset(dataset_path, output_path, profile='auto', profile_config=None, exclude_paths=None):
    from .profiles import load_profiles, apply_profiles
    profiles = load_profiles(profile_config)
    root = Path(dataset_path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Dataset path must be a directory')
    output = Path(output_path).expanduser().resolve()
    if output == root or output in root.parents:
        raise ValueError('Output must not equal or contain the dataset directory')
    if profile not in {'auto','existing_system','celloger'}:
        raise ValueError('Unsupported imaging profile')
    output.mkdir(parents=True, exist_ok=True)
    # A new import directory avoids replacing previous inventories.
    destination = output / ('import-' + uuid.uuid4().hex)
    destination.mkdir()
    dataset_uid = identity('dataset:'+str(root))
    manifest = dict(import_version=VERSION,dataset_uid=dataset_uid,dataset_root=str(root),
                    scanned_at=datetime.now(timezone.utc).isoformat(), requested_profile=profile,
                    detected_profile='unknown',profile_selection_source='unknown',files=[],images=[],warnings=[],errors=[])
    raw_records=[]
    def walk_error(exc):
        manifest['errors'].append({'path':str(exc.filename),'message':str(exc)})
    excluded={Path(p).expanduser().resolve() for p in (exclude_paths or [])}
    candidates=[]
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d.lower() not in {'processed','1_processeddata'} and (Path(directory)/d).resolve() not in excluded and not (Path(directory)/d).is_symlink() and (Path(directory)/d).resolve()!=output)
        for name in sorted(names):
            path=Path(directory)/name
            if path.is_symlink() or name.startswith('.') or path.resolve() in excluded:
                continue
            if path.suffix.lower() in SUPPORTED | PROPRIETARY:
                candidates.append(path)
    detected=set()
    for path in candidates:
        relative=path.relative_to(root).as_posix()
        entry={'path':relative,'status':'pending'}
        manifest['files'].append(entry)
        if path.suffix.lower() in PROPRIETARY:
            entry.update(status='unsupported',reason='Vendor-format reader is not configured; export TIFF/OME-TIFF or add a reader.')
            continue
        try:
            before=path.stat()
            if getattr(before,'st_flags',0) & getattr(stat,'SF_DATALESS',0):
                raise ValueError('Online-only cloud file. Make this file available offline, then import again.')
            checksum=digest(path)
            series_list=inspect_image(path,root)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('File changed during import; retry after acquisition/export completes')
            entry.update(status='readable',inspection_level='headers_and_metadata',sha256=checksum,size_bytes=after.st_size,series_count=len(series_list))
            for series in series_list:
                metadata=series.pop('metadata')
                evidence=' '.join(str(v) for v in metadata['values'].values() if v).lower()
                source='celloger' if 'celloger' in evidence or 'celloger' in str(series['raw_metadata'].get('tiff_software','')).lower() else 'unknown'
                if source!='unknown':detected.add(source)
                sequence=identity(dataset_uid+':'+relative+':series:'+str(series['series_index']))
                raw_index=len(raw_records)
                raw_records.append({'source_path':relative,'series_index':series['series_index'],
                                    'embedded':series.pop('raw_metadata'),'sidecars':series.pop('sidecars')})
                for frame in range(series.pop('frame_count')):
                    image_uid=identity(sequence+':'+checksum+':frame:'+str(frame))
                    manifest['images'].append(dict(image_uid=image_uid,sequence_uid=sequence,
                        image_relative_path=relative,frame_index=frame,**series,
                        imaging_source=profile if profile!='auto' else source,
                        imaging_metadata=metadata['values'],imaging_metadata_provenance=metadata['provenance'],
                        metadata_conflicts=metadata['conflicts'],warnings=metadata['warnings'],
                        raw_metadata_record_index=raw_index,
                        grouping_status='within_file_only',
                        acquired_at=series['acquisition'].get('acquired_at_frame_zero') if frame==0 else None))
        except Exception as exc:
            entry.update(status='error',reason=str(exc))
            manifest['errors'].append({'path':relative,'message':str(exc)})
    if profile!='auto':
        manifest['detected_profile']=profile;manifest['profile_selection_source']='user_supplied'
        if detected and profile not in detected:
            manifest['warnings'].append('Selected profile conflicts with detected Celloger metadata; review before analysis.')
    elif len(detected)==1 and all(i['imaging_source']!='unknown' for i in manifest['images']):
        manifest['detected_profile']=next(iter(detected));manifest['profile_selection_source']='metadata'
    if not manifest['images']:manifest['warnings'].append('No readable images found.')
    if any(i['imaging_source']=='unknown' for i in manifest['images']):manifest['warnings'].append('Some images lack recognizable device metadata; select an imaging profile.')
    apply_profiles(manifest, raw_records, profiles, profile)
    chosen=profile if profile!='auto' else manifest.get('selected_profile')
    registration=profiles.get(chosen,{}).get('registration',{})
    if registration.get('enabled') and registration.get('group_by_well_field') and manifest['images']:
        from .well_series import group_well_series
        try:
            group_well_series(manifest)
            manifest['series_summary']['field_suffix_status']=registration['field_suffix_status']
        except ValueError as exc:
            manifest['registration_grouping_error']=str(exc)
            manifest['warnings'].append(str(exc))
    if any(i['grouping_status']=='within_file_only' for i in manifest['images']):
        manifest['warnings'].append('Some files remain separate sequences; configure a filename grouping rule if needed.')
    manifest['summary']={'image_files':len(candidates),'logical_frames':len(manifest['images']),
                         'readable_files':sum(f['status']=='readable' for f in manifest['files']),
                         'unsupported_files':sum(f['status']=='unsupported' for f in manifest['files']),
                         'error_files':sum(f['status']=='error' for f in manifest['files'])}
    (destination/'dataset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'raw_metadata.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in raw_records))
    return manifest,destination

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset_path');parser.add_argument('--output',required=True)
    parser.add_argument('--profile',choices=['auto','existing_system','celloger'],default='auto')
    parser.add_argument('--profile-config',help='Saved JSON profile overriding one built-in imaging profile')
    args=parser.parse_args()
    try:
        manifest,destination=scan_dataset(args.dataset_path,args.output,args.profile,args.profile_config)
    except (OSError,ValueError) as exc:
        parser.exit(2,str(exc)+'\n')
    print(json.dumps({'output':str(destination),**manifest['summary'],'configuration':manifest['configuration_summary'],'warnings':manifest['warnings']},indent=2))
    return 1 if manifest['errors'] or not manifest['images'] else 0

if __name__=='__main__':
    raise SystemExit(main())
