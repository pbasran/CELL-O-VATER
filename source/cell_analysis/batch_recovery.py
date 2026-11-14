"""Verified resume and cleanup of regenerable scratch data only."""
import hashlib,json
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def verify_publication(folder):
 folder=Path(folder).resolve();complete=json.loads((folder/'COMPLETE.json').read_text());pub=json.loads((folder/'run_manifest.json').read_text())
 if complete['status']!='complete' or pub['measurement_summary']['status']!='complete':raise ValueError('Published run is incomplete')
 if complete['cell_count']!=pub['measurement_summary']['cell_count']:raise ValueError('Published count mismatch')
 root=Path(pub['layout']['processed_root']).resolve()
 for rel,expected in pub['files_sha256'].items():
  path=(root/rel).resolve()
  if not path.is_relative_to(root) or sha(path)!=expected:raise ValueError('Published output verification failed: '+str(path))
 return complete,pub

def resumable(item,options,model_hash):
 folder=Path(item['results_folder'])
 if not (folder/'COMPLETE.json').exists():
  if (folder/'run_manifest.json').exists():raise ValueError('Existing published results lack a completion marker; review required, not reprocessing')
  return None
 complete,pub=verify_publication(folder);seg=pub['segmentation']
 if seg['options']!=options or seg['model_sha256']!=model_hash:raise ValueError('Existing result uses different settings/model; resume will not overwrite it')
 images=seg['images']
 if {i['source_path'] for i in images}!=set(item['files']):raise ValueError('Existing result inventory differs from selected input')
 for image in images:
  path=Path(item['source'])/image['source_path']
  if sha(path)!=image['source_sha256']:raise ValueError('Source image changed; existing result will not be reused: '+str(path))
 return {'folder':item['folder'],'status':'complete','preexisting':True,'image_count':complete['image_count'],'cell_count':complete['cell_count'],'output':str(folder),'resume_verification':'Source, settings, model and published file hashes verified'}

def cleanup_scratch(segmentation,published,work_root,remove_published_copies=False):
 seg=Path(segmentation).resolve();work=Path(work_root).resolve()
 if seg.parent!=work or not seg.name.startswith('segmentation-'):raise ValueError('Cleanup path is not a generated segmentation folder')
 complete,pub=verify_publication(published);manifest=json.loads((seg/'segmentation_manifest.json').read_text());meas=Path(manifest['measurements']['output_directory']).resolve()
 if meas.parent!=work or not meas.name.startswith('cellprofiler-'):raise ValueError('Invalid measurement scratch folder')
 files=list((seg/'inputs').glob('*.npy'))+list((meas/'inputs').glob('*.tif'))
 if remove_published_copies:
  # Remove only byte-identical copies present in the verified publication.
  published_hashes=set(pub['files_sha256'].values())
  for directory in ['masks','overlays','registered_images','analysis_regions']:
   for path in (seg/directory).glob('*'):
    if path.is_file() and not path.is_symlink() and sha(path) in published_hashes:files.append(path)
 archive=seg/'segmentation_results.zip'
 if archive.exists():files.append(archive)
 # Retain logs, manifests and tables. Remove only inputs and duplicate archive.
 size=sum(p.stat().st_size for p in files)
 for p in files:p.unlink()
 report={'verified_publication':str(published),'removed_generated_files':len(files),'bytes_recovered':size}
 (seg/'scratch_cleanup.json').write_text(json.dumps(report,indent=2));return report
