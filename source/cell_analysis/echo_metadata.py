"""Read the ECHO fields observed in the supplied Revolve TIFF exports."""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime


def extract_echo(page,meta,reference):
    from .importer import record
    software=page.tags.get(305)
    software=str(software.value) if software else ''
    if not software.startswith('ECHO Pro '):return {},{}
    match=re.fullmatch(r'ECHO Pro v([^ ]+) \(Build ([^)]+)\)',software)
    if match:
        for key,value in [('acquisition_software_name','ECHO Pro'),('acquisition_software_version',match[1]),('acquisition_software_build',match[2])]:
            record(meta,key,value,'embedded_metadata',reference,'TIFF/Software')
    exif=page.tags.get(34665)
    exif=exif.value if exif else {}
    raw=exif.get('UserComment','')
    if isinstance(raw,bytes):raw=raw.removeprefix(b'ASCII\x00\x00\x00').decode('utf-8',errors='replace')
    try:values=json.loads(raw)
    except (TypeError,ValueError):values={}
    for source,key in [('microscopeModel','imaging_device_model'),('microscopeStandNumber','imaging_device_name')]:
        record(meta,key,values.get(source),'embedded_metadata',reference,'EXIF/UserComment/'+source)
    for tag,key in [(271,'camera_manufacturer'),(272,'camera_model')]:
        value=page.tags.get(tag)
        if value:record(meta,key,value.value,'embedded_metadata',reference,'TIFF/'+str(tag))
    details={'objective_magnification':values.get('objectiveMag'),'reported_effective_pixel_size':values.get('effectivePixelSize'),'reported_pixel_size_unit':None}
    if values.get('effectivePixelSize') is not None:meta['warnings'].append('ECHO effectivePixelSize retained; physical units and scale require confirmation.')
    original=exif.get('DateTimeOriginal')
    if original:
        try:details['acquisition_local_time']=datetime.strptime(original,'%Y:%m:%d %H:%M:%S').isoformat()
        except ValueError:pass
    xmp=page.tags.get(700)
    xml=xmp.value if xmp else None
    if xml:
        try:
            root=ET.fromstring(xml.rstrip(b'\x00') if isinstance(xml,bytes) else xml.rstrip('\x00'))
            created=next((e.text for e in root.iter() if e.tag=='{http://ns.adobe.com/xap/1.0/}CreateDate'),None)
            parsed=datetime.fromisoformat(created) if created else None
            original=exif.get('DateTimeOriginal')
            if parsed and parsed.tzinfo and original and parsed.strftime('%Y:%m:%d %H:%M:%S')==original:
                details['acquired_at_frame_zero']=parsed.isoformat()
        except (ET.ParseError,ValueError):meta['warnings'].append('Could not normalize ECHO acquisition timestamp.')
    return details,{'exif':{k:str(v) for k,v in exif.items()},'xmp':xml.decode('utf-8',errors='replace') if isinstance(xml,bytes) else xml,'echo_user_comment':values}
