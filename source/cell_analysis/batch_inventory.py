"""Inventory microscopy folders without loading image pixels."""
from pathlib import Path
import re
from .mirrored_outputs import layout,raw_anchor
IMAGE_EXT={'.tif','.tiff','.jpg','.jpeg','.png'}

def inventory(source,output):
    root=Path(source).expanduser().resolve();target=Path(output).expanduser().resolve()
    if not root.is_dir():raise ValueError('Input folder does not exist')
    if target==root or target.is_relative_to(root) or root.is_relative_to(target):raise ValueError('Input and output folders must be separate; neither may contain the other')
    batches={};excluded=[];review=[]
    for image in sorted(root.rglob('*')):
        if not image.is_file() or image.is_symlink() or image.suffix.lower() not in IMAGE_EXT:continue
        if any(part.startswith('.') for part in image.relative_to(root).parts):continue
        ancestors=[image.parent,*image.parent.parents]
        chain=[]
        for parent in ancestors:
            chain.append(parent)
            if parent==root:break
        # Explicit instrument fields in the nearest README take precedence.
        tool=None
        for parent in chain:
            readme=next((p for p in parent.iterdir() if p.name.casefold()=='readme.md' and p.is_file()),None)
            if readme:
                text=readme.read_text(errors='replace')
                lines=[line for line in text.splitlines() if re.search(r'(source|instrument|system|tool)\s*[:/]|source/instrument/system',line,re.I)]
                declarations=' '.join(lines)
                if re.search(r'\b(EPSO|EPSON|flatbed)\b',declarations,re.I):tool='EPSO';break
                if re.search(r'\b(ECHO|Revolve)\b',declarations,re.I):tool='ECHO';break
            if parent.name.upper().startswith(('EPSO_','EPSON_')):tool='EPSO';break
            if parent.name.upper().startswith('ECHO_'):tool='ECHO';break
        relative=image.relative_to(root).as_posix()
        if tool=='EPSO':excluded.append(relative);continue
        if tool!='ECHO':review.append(relative);continue
        leaf=image.parent;key=leaf.relative_to(root).as_posix()
        # Existing 0_RawData convention retains all raw-relative ancestors.
        destination=target if raw_anchor(leaf).name.casefold()=='0_rawdata' else target/leaf.relative_to(root)
        result=layout(leaf,destination)['results_folder']
        row=batches.setdefault(key,{'folder':key,'source':str(leaf),'destination':str(destination),'results_folder':result,'files':[]})
        row['files'].append(image.name)
    rows=list(batches.values())
    if not rows:raise ValueError('No ECHO images found. Identify the instrument in README.md or use ECHO_ acquisition folders. EPSO scans are excluded.')
    return {'input':str(root),'output':str(target),'batches':rows,'image_count':sum(len(b['files']) for b in rows),'excluded':excluded,'unclassified':review}
