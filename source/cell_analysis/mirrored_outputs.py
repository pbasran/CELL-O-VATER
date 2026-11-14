"""Mirror raw-relative image paths; preserve README evidence and version prior outputs."""
import csv, hashlib, io, json, os, re, shutil, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def raw_anchor(source):
    source=Path(source).expanduser().resolve()
    return next((p for p in [source,*source.parents] if p.name.casefold()=='0_rawdata'),source)


def layout(source, requested=None):
    source=Path(source).expanduser().resolve();anchor=raw_anchor(source)
    if requested:
        target=Path(requested).expanduser().resolve()
    elif anchor.name.casefold()=='0_rawdata':target=anchor.parent/'1_ProcessedData'
    else:raise ValueError('Select a folder inside 0_RawData, or specify a separate processed-data root. No output will be written inside the source folder.')
    if target==anchor or target.is_relative_to(anchor) or anchor.is_relative_to(target):
        raise ValueError('Processed-data root must be separate from the raw-data tree; neither folder may contain the other.')
    return {'raw_root':str(anchor),'source_folder':str(source),'processed_root':str(target),'relative_path':source.relative_to(anchor).as_posix(),'results_folder':str(target/source.relative_to(anchor))}


def _sha(data):return hashlib.sha256(data).hexdigest()
def _json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def _key(text):return re.sub(r'[^a-z0-9]+','_',text.strip().strip('*').lower()).strip('_')


def parse_readme(text):
    """Only explicit key:value lines and two-column tables. Never execute or infer prose."""
    fields=[];fence=False
    for line in text.splitlines():
        if line.strip().startswith(('```','~~~')):fence=not fence;continue
        if fence:continue
        clean=re.sub(r'^\s*[-*+]\s+','',line).strip()
        if clean.startswith('|'):
            parts=[p.strip() for p in clean.strip('|').split('|')]
            if len(parts)!=2 or _key(parts[0]) in {'field','key','metadata','parameter'} or set(parts[0])<={'-',':',' '}:continue
            k,v=parts
        elif ':' in clean and not clean.startswith('#'):
            k,v=clean.split(':',1)
        else:continue
        k=k.strip().strip('*');v=v.strip().strip('*').strip()
        if k and v and len(k)<100:fields.append({'key':_key(k),'label':k,'value':v})
    return fields


def snapshot_readmes(manifest):
    source=Path(manifest['dataset_root']).resolve();anchor=raw_anchor(source);base=anchor.parent if anchor.name.casefold()=='0_rawdata' else anchor
    records={};by_image={};warnings=set()
    for im in manifest['images']:
        image=(source/im['image_relative_path']).resolve()
        if not image.is_relative_to(anchor):raise ValueError('Image path escapes raw-data root')
        dirs=[]
        p=image.parent
        while p.is_relative_to(base):
            dirs.append(p)
            if p==base:break
            p=p.parent
        paths=[]
        for directory in reversed(dirs):
            if not directory.is_dir():
                warnings.add('README source folder unavailable: '+str(directory));continue
            for readme in sorted(directory.iterdir()):
                if readme.name.casefold()!='readme.md' or not readme.is_file():continue
                if readme.is_symlink():continue
                key=readme.relative_to(base).as_posix();paths.append(key)
                if key not in records:
                    data=readme.read_bytes()
                    if len(data)>4*1024*1024:raise ValueError('README exceeds 4 MB: '+str(readme))
                    text=data.decode('utf-8-sig')
                    records[key]={'source_path':str(readme),'relative_path':key,'sha256':_sha(data),'text':text,'fields':parse_readme(text),'encoding':'utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8'}
        by_image[im['image_uid']]=paths
    return {'captured_at':datetime.now(timezone.utc).isoformat(),'records':records,'by_image':by_image,'warnings':sorted(warnings),'policy':'Explicit fields only. Conflicting values remain unresolved. Prose is preserved in source snapshots.'}


def image_metadata(im,snapshot):
    evidence={}
    for source in snapshot['by_image'].get(im.get('source_image_uid',im['image_uid']),[]):
        for field in snapshot['records'][source]['fields']:
            evidence.setdefault(field['key'],[]).append({'value':field['value'],'source':source})
    resolved={};conflicts={}
    embedded=im.get('imaging_metadata',{})
    for key,values in evidence.items():
        actual=embedded.get(key)
        if actual is not None:values=values+[{'value':str(actual),'source':'embedded_image_metadata'}]
        distinct={v['value'] for v in values}
        if len(distinct)==1:resolved[key]=values[0]['value']
        else:conflicts[key]=values
    return {'readme_fields':resolved,'readme_evidence':evidence,'metadata_conflicts':conflicts,'embedded_image_metadata':embedded}


def _table(path,rows,columns=None):
    columns=columns or list(dict.fromkeys(k for r in rows for k in r)) or ['cell_uid','image_uid','mask_label']
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        writer.writerows({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)


def publish(segmentation, measurements, target, dataset_root):
    seg=Path(segmentation);meas=Path(measurements)
    summary=json.loads((meas/'summary.json').read_text())
    if summary.get('status')!='complete':raise ValueError('Measurements must finish before publishing')
    config=layout(dataset_root,str(target));anchor=Path(config['raw_root']);source=Path(config['source_folder']);target=Path(config['processed_root'])
    selected=source.relative_to(anchor)
    manifest=json.loads((seg/'segmentation_manifest.json').read_text());imp=json.loads((seg/'import_manifest.json').read_text())
    snapshot=imp.get('readme_metadata') or snapshot_readmes(imp)
    imports={im['image_uid']:im for im in imp['images']}
    rows=json.loads((meas/'cells.json').read_text())
    if len(rows)!=summary['cell_count']:raise ValueError('Cell table count disagrees with measurement summary')
    run=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:10]
    target.mkdir(parents=True,exist_ok=True);stage=target/('.cell-o-vater-'+run+'.partial');stage.mkdir()
    entries=[];all_rows=[];duplicates=Counter(im['source_path'] for im in manifest['images'])
    for index,im in enumerate(manifest['images']):
        raw=(source/im['source_path']).resolve()
        if not raw.is_relative_to(source):raise ValueError('Image escapes selected source folder')
        rel=raw.relative_to(anchor);folder=rel
        if duplicates[im['source_path']]>1:folder=folder/('frame-'+str(im.get('frame_index',index))+'-'+im['image_uid'])
        dest=stage/folder;dest.mkdir(parents=True,exist_ok=True)
        original=imports.get(im.get('source_image_uid',im['image_uid']),{})
        md=image_metadata({**im,**original},snapshot)
        cells=[dict(r) for r in rows if r['image_index']==index]
        if len(cells)!=im['object_count']:raise ValueError('Per-image cell count mismatch: '+im['source_path'])
        for row in cells:
            row['raw_relative_path']=rel.as_posix()
            row.update({'readme_'+k:v for k,v in md['readme_fields'].items()})
            row['readme_metadata_conflicts']=md['metadata_conflicts']
        all_rows.extend(cells);_table(dest/'cells.csv',cells);_json(dest/'cells.json',cells)
        for key,name in [('mask_relative_path','segmentation_mask.tif'),('overlay_relative_path','overlay.png')]:
            path=(seg/im[key]).resolve()
            if not path.is_relative_to(seg.resolve()):raise ValueError('Invalid segmentation artifact path')
            shutil.copy2(path,dest/name)
        for directory,name in [('registered_images','registered_image.tif'),('analysis_regions','analysis_region.tif')]:
            path=seg/directory/f'{index:06d}.tif'
            if path.exists():shutil.copy2(path,dest/name)
        metadata={**md,'image':im,'raw_relative_path':rel.as_posix(),'run_uid':run,'source_readmes':snapshot['by_image'].get(original.get('image_uid'),[]),'cell_count':len(cells),'review_status':'provisional','physical_units':'pixels unless verified calibration is supplied'}
        _json(dest/'metadata.json',metadata)
        entries.append({'image_uid':im['image_uid'],'source_path':im['source_path'],'raw_relative_path':rel.as_posix(),'output_folder':folder.as_posix(),'cell_count':len(cells),'well_id':im.get('well_id'),'acquired_at':im.get('acquired_at') or im.get('acquisition_local_time'),'readme_fields':md['readme_fields'],'metadata_conflicts':md['metadata_conflicts']})
    root=stage/selected;root.mkdir(parents=True,exist_ok=True)
    for key,record in snapshot['records'].items():
        path=root/'.source_metadata'/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(record['text'].encode(record['encoding']))
    _json(root/'metadata.json',{'layout':config,'readme_metadata':snapshot,'images':entries})
    _table(root/'cells_all_images.csv',all_rows);_json(root/'cells_all_images.json',all_rows)
    for name in ['provenance.json','measurements.cppipe']:
        if (meas/name).exists():shutil.copy2(meas/name,root/name)
    # Original executed pipeline is provenance; its absolute working-input paths are retained.
    reports={selected,*[Path(e['raw_relative_path']).parent for e in entries]}
    for relative in reports:
        directory=stage/relative;directory.mkdir(parents=True,exist_ok=True)
        members=[e for e in entries if Path(e['raw_relative_path']).is_relative_to(relative)]
        lines=['# Image analysis results','',f'Run: `{run}`',f'Source: `{source}`',f'Completed: {datetime.now(timezone.utc).isoformat()}',f"Model: {manifest.get('model')} · Cellpose {manifest.get('engine_version')}",f"Images analyzed: {len(members)} · Segmented objects: {sum(e['cell_count'] for e in members)}",f"Measurement features per object: {summary.get('feature_count')}",'','Counts are segmented objects across images, not distinct tracked biological cells. Segmentation review is provisional; physical dimensions remain in pixels.','', '## Image outputs','','| Image | Well | Acquisition time | Objects | Metadata conflicts | Outputs |','|---|---|---|---:|---:|---|']
        for e in members:
            f=Path(e['output_folder']).relative_to(relative).as_posix()
            links=' · '.join(f'[{label}]({quote(f+"/"+file,safe="/")})' for label,file in [('Features','cells.csv'),('Metadata','metadata.json'),('Overlay','overlay.png'),('Mask','segmentation_mask.tif')])
            safe=lambda v:str(v or 'Not recorded').replace('|','\\|').replace('\n',' ')
            lines.append(f"| {safe(e['raw_relative_path'])} | {safe(e['well_id'])} | {safe(e['acquired_at'])} | {e['cell_count']} | {len(e['metadata_conflicts'])} | {links} |")
        if relative==selected:
            lines+=['','[Combined cell table](cells_all_images.csv) · [Run manifest](run_manifest.json) · [Full metadata](metadata.json)','','## README metadata','']
            if not snapshot['records']:lines+=['README metadata could not be fully checked; see warnings below.' if snapshot.get('warnings') else 'No applicable README.md files were found.']
            lines+=['- '+w for w in snapshot.get('warnings',[])]
            for key,record in snapshot['records'].items():
                lines+=[f'### [{key}]({quote(".source_metadata/"+key,safe="/")})','']
                lines += [f"- {f['label']}: {f['value']}" for f in record['fields']] or ['No explicit key/value fields parsed; consult the preserved README.']
            lines+=['','Conflicting metadata is retained with provenance and left unresolved. Folder names are preserved without inferring their meaning.','','## Processing settings','', '```json',json.dumps(manifest.get('options',{}),indent=2),'```','','## Import and QC notes','']
            lines += ['- '+str(w) for w in imp.get('warnings',[])] or ['No import warnings.']
            lines += [f"- Import: {imp.get('summary',{}).get('image_files','unknown')} images found; {imp.get('summary',{}).get('error_files',0)} file errors. Analysis covers the images listed above.",'- Registration: translation only; a single marker does not establish rotation or scale.','- Executed CellProfiler pipeline is retained for provenance; its working-input paths are not portable.']
        if relative!=selected:_json(directory/'metadata.json',{'run_uid':run,'images':members,'source_relative_folder':relative.as_posix()})
        (directory/'results.md').write_text('\n'.join(lines)+'\n')
    inventory={p.relative_to(stage).as_posix():_sha(p.read_bytes()) for p in stage.rglob('*') if p.is_file()}
    _json(root/'run_manifest.json',{'run_uid':run,'status':'complete','layout':config,'images':entries,'segmentation':manifest,'measurement_summary':summary,'files_sha256':inventory})
    _json(root/'COMPLETE.json',{'run_uid':run,'status':'complete','cell_count':len(rows),'image_count':len(entries),'summary':'results.md','table':'cells_all_images.csv'})
    # Install only generated files, retaining unrelated results; roll back partial commits.
    generated=[p for p in stage.rglob('*') if p.is_file()]
    generated.sort(key=lambda p:(p.name=='COMPLETE.json',str(p)))
    installed=[];backups=[];history=target/'.history'/run
    try:
        # Remove the prior completion marker before changing any visible output.
        for path in generated:
            dest=target/path.relative_to(stage)
            if not dest.resolve().is_relative_to(target.resolve()):raise ValueError('Output path escapes processed-data root')
            if path.name=='COMPLETE.json' and dest.exists():
                backup=history/path.relative_to(stage);backup.parent.mkdir(parents=True,exist_ok=True);os.replace(dest,backup);backups.append((backup,dest))
        for path in generated:
            relative=path.relative_to(stage);dest=target/relative
            if not dest.resolve().is_relative_to(target.resolve()):raise ValueError('Output path escapes processed-data root')
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():
                if not dest.is_file():raise ValueError('Output file collides with an existing folder: '+str(dest))
                backup=history/relative;backup.parent.mkdir(parents=True,exist_ok=True);os.replace(dest,backup);backups.append((backup,dest))
            os.replace(path,dest);installed.append(dest)
    except Exception:
        for path in reversed(installed):path.unlink()
        for backup,dest in reversed(backups):os.replace(backup,dest)
        raise
    shutil.rmtree(stage)
    return str(target/selected)
