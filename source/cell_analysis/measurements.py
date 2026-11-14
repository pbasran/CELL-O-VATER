"""CellProfiler measurements of externally supplied SAM instance masks."""
import csv,hashlib,json,os,subprocess,uuid
from time import perf_counter
from pathlib import Path
from datetime import datetime,timezone
from .profiles import BASE
CP=BASE/'runtimes/cellprofiler/CellProfiler.app/Contents/MacOS/cp'
JAVA=BASE/'runtimes/java/jdk8u504-b01-jre/Contents/Home'
from .working_storage import WORK_ROOT
CURRENT=WORK_ROOT/'current-measurements.json'
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def atomic(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');tmp.replace(path)
def pipeline(out):
 modules=[('LoadData',6,[f'Elsewhere...|{out}','inputs.csv','Yes','Default Input Folder|','No','1,100000','No','','No']),('MeasureObjectSizeShape',3,['Cells','Yes','Yes']),('MeasureObjectIntensity',4,['Source','Cells']),('MeasureTexture',7,['Source','Cells','32','1','Objects','3']),('MeasureObjectNeighbors',3,['Cells','Cells','Within a specified distance','20','No','No','NeighborCount','Default','No','Touching','Default']),('ExportToSpreadsheet',13,['Comma (",")','Yes','No','No','No','No','No','Default Output Folder|','No','Metadata','None','None','Yes','','Null','No','','Yes','Cells','No','Cells.csv','Yes'])]
 s='CellProfiler Pipeline: http://www.cellprofiler.org\nVersion:5\nDateRevision:428\nGitHash:\nModuleCount:6\nHasImagePlaneDetails:False\n\n'
 for n,(name,rev,values) in enumerate(modules,1):
  s+=f"{name}:[module_num:{n}|svn_version:'Unknown'|variable_revision_number:{rev}|show_window:False|notes:[]|batch_state:array([], dtype=uint8)|enabled:True|wants_pause:False]\n"
  s+=''.join(f'    Setting {i}:{value}\n' for i,value in enumerate(values))+'\n'
 (out/'measurements.cppipe').write_text(s)
def intensity_scale(dtype):
 if dtype not in {'uint8','uint16','RGB','RGBA','L'}:raise ValueError('Measurement intensity scaling requires uint8 or uint16 source metadata')
 return 65535 if dtype=='uint16' else 255

def run(source_run=None):
 import numpy as np,tifffile
 from scipy.ndimage import distance_transform_edt
 trial=BASE/'outputs/cellpose-sam-full'
 is_trial=source_run is None
 if is_trial:
  experiment=json.loads((trial/'experiment.json').read_text());source=Path(experiment['source_run']);model_hash=experiment['model_sha256'];mask_paths=[trial/f'{i}-labels.tif' for i in range(3)]
  if json.loads((trial/'status.json').read_text())['status']!='complete':raise ValueError('SAM run is incomplete')
 else:
  source=Path(source_run);experiment=json.loads((source/'segmentation_manifest.json').read_text());model_hash=experiment['model_sha256'];mask_paths=[source/im['mask_relative_path'] for im in experiment['images']]
 manifest=json.loads((source/'segmentation_manifest.json').read_text())
 imp=json.loads((source/'import_manifest.json').read_text()) if (source/'import_manifest.json').exists() else json.loads(Path(json.loads((BASE/'local_settings.json').read_text())['last_import']).read_text())
 metadata={im['image_uid']:im for im in imp['images']}
 hashes=[digest(p) for p in mask_paths];seg_uid=str(uuid.uuid5(uuid.NAMESPACE_URL,manifest['run_uid']+model_hash+''.join(hashes)))
 out=WORK_ROOT/('cellprofiler-'+str(uuid.uuid4()));out.mkdir();(out/'inputs').mkdir()
 timing_started=perf_counter();timings={}
 atomic(CURRENT,{'status':'running','output_directory':str(out),'stage':'Preparing CellProfiler inputs'})
 identity=[];inputs=[];expected={}
 try:
  for index,mask_path in enumerate(mask_paths):
   image=manifest['images'][index];labels=tifffile.imread(mask_path);raw=tifffile.imread(source/f'registered_images/{index:06d}.tif');valid=tifffile.imread(source/f'analysis_regions/{index:06d}.tif').astype(bool)
   if raw.shape!=labels.shape or not np.isfinite(raw).all() or labels[~valid].any():raise ValueError('Source, labels or analysis region failed validation')
   unique=np.unique(labels);unique=unique[unique>0];cp_labels=np.zeros(labels.shape,np.uint16);distance=distance_transform_edt(valid);meta=metadata.get(image.get('source_image_uid',image['image_uid']),{});time=image.get('acquired_at');ac=meta.get('acquisition',{})
   scale=intensity_scale(meta.get('dtype'))
   if raw.min()<0 or raw.max()>scale:raise ValueError('Source values exceed recorded intensity range')
   if len(unique)>65535:raise ValueError('Too many objects for CellProfiler label export')
   for number,label in enumerate(unique,1):
    region=labels==label;cp_labels[region]=number;yy,xx=np.nonzero(region)
    cell_uid='U-'+str(uuid.uuid5(uuid.UUID(seg_uid),image['image_uid']+':'+str(int(label))))
    row={'cell_uid':cell_uid,'identity_scope':'segmentation_run_image_object','segmentation_run_uid':seg_uid,'image_uid':image['image_uid'],'image_index':index,'cp_image_number':index+1,'cp_object_number':number,'mask_label':int(label),'source_path':image['source_path'],'source_sha256':image['source_sha256'],'mask_sha256':hashes[index],'well_id':image.get('well_id'),'field_id':image.get('field_id'),'acquired_at':time,'acquisition_date':time[:10] if time else None,'acquisition_local_time':image.get('acquisition_local_time'),'parent_cell_uid':None,'track_uid':None,'lineage_status':'unassigned','origin':'unknown','generation':None,'probability_of_death':None,'predicted_death_phase':None,'prediction_status':'not_computed','tags':{},'coordinate_space':'registered_reference_pixels' if image.get('registration') else 'source_image_pixels','distance_to_excluded_area_px':float(distance[region].min()),'qc_near_exclusion_20px':bool(distance[region].min()<=20),'qc_touches_image_border':bool((xx==0).any() or (yy==0).any() or (xx==raw.shape[1]-1).any() or (yy==raw.shape[0]-1).any()),'qc_segmentation_review':'provisional','pixel_size_unit':ac.get('reported_pixel_size_unit'),'pixel_size_um':None,'intensity_basis':f'source_grayscale_divided_by_{scale}','measurement_engine':'CellProfiler 4.2.8','cell_type':'OSCA' if is_trial else None,**meta.get('imaging_metadata',{})}
    expected[(index+1,number)]={'area':len(xx),'mean':float(raw[region].mean()/scale),'x':float(xx.mean()),'y':float(yy.mean())};identity.append(row)
   tifffile.imwrite(out/f'inputs/{index}-labels.tif',cp_labels,photometric='minisblack')
   tifffile.imwrite(out/f'inputs/{index}-source.tif',raw.astype(np.float32)/scale,photometric='minisblack')
   inputs.append({'Image_FileName_Source':f'{index}-source.tif','Image_PathName_Source':str(out/'inputs'),'Image_ObjectsFileName_Cells':f'{index}-labels.tif','Image_ObjectsPathName_Cells':str(out/'inputs'),'Metadata_ImageUID':image['image_uid']})
  with (out/'inputs.csv').open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=list(inputs[0]));writer.writeheader();writer.writerows(inputs)
  atomic(out/'identity-map.json',identity);pipeline(out)
  atomic(out/'provenance.json',{'segmentation_run_uid':seg_uid,'model_sha256':model_hash,'mask_sha256':hashes,'source_run':str(source),'sam_trial':is_trial,'pipeline_sha256':digest(out/'measurements.cppipe'),'measurement_input':'Registered grayscale source, no contrast enhancement or illumination correction, scaled by the unsigned source dtype range. Registration interpolation, when used, is retained.','physical_calibration':'Unknown; shape and distance features are pixels.','lineage':'U prefix means origin unknown. No temporal tracking, seeded/daughter assignment or death prediction has been inferred.'})
  atomic(CURRENT,{'status':'running','output_directory':str(out),'stage':'Running CellProfiler'})
  timings['input_preparation_seconds']=perf_counter()-timing_started;timing_started=perf_counter()
  env=os.environ.copy();env['JAVA_HOME']=str(JAVA)
  with (out/'cellprofiler.log').open('w') as log:
   result=subprocess.run([str(CP),'-c','-r','-p',str(out/'measurements.cppipe'),'-o',str(out),'-d',str(out/'done.txt')],env=env,stdout=log,stderr=subprocess.STDOUT)
  timings['cellprofiler_process_seconds']=perf_counter()-timing_started;timing_started=perf_counter()
  if result.returncode or not (out/'Cells.csv').exists():raise RuntimeError('CellProfiler did not produce Cells.csv; see cellprofiler.log')
  reader=csv.DictReader((out/'Cells.csv').open());cp_rows=list(reader);joined=[];seen=set();features={}
  feature_names=[k for k in reader.fieldnames if k not in {'ImageNumber','ObjectNumber'} and not k.startswith('Metadata_')]
  by_key={(r['cp_image_number'],r['cp_object_number']):r for r in identity}
  for cp in cp_rows:
   key=(int(cp['ImageNumber']),int(cp['ObjectNumber']))
   if key not in by_key or key in seen:raise ValueError('CellProfiler object mapping is inconsistent')
   seen.add(key);exp=expected[key]
   checks=[('AreaShape_Area',exp['area'],.01),('Intensity_MeanIntensity_Source',exp['mean'],1e-5),('Location_Center_X',exp['x'],.01),('Location_Center_Y',exp['y'],.01)]
   for name,value,tol in checks:
    if abs(float(cp[name])-value)>tol:raise ValueError(f'Measurement mapping or scaling failed: {key} {name}')
   features={}
   for k,value in cp.items():
    if k in {'ImageNumber','ObjectNumber'} or k.startswith('Metadata_'):continue
    try:value=float(value) if value else None
    except ValueError:pass
    if isinstance(value,float) and not np.isfinite(value):value=None
    features[k]=value
   joined.append({**by_key[key],**features})
  if seen!=set(by_key):raise ValueError('CellProfiler output is missing cells')
  columns=list(dict.fromkeys(k for row in joined for k in row)) or ['cell_uid',*feature_names]
  with (out/'cells.csv').open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows({k:json.dumps(v) if isinstance(v,dict) else v for k,v in row.items()} for row in joined)
  atomic(out/'cells.json',joined)
  info={'status':'complete','output_directory':str(out),'segmentation_run_uid':seg_uid,'cell_count':len(joined),'column_count':len(columns),'feature_count':len(feature_names),'per_image_counts':[sum(r['image_index']==i for r in joined) for i in range(len(inputs))],'completed_at':datetime.now(timezone.utc).isoformat(),'verified':'One-to-one label mapping, area, centroid and source intensity checks passed for every object.'}
  timings['verification_and_export_seconds']=perf_counter()-timing_started;info['timings']=timings;atomic(out/'timing.json',timings)
  atomic(out/'summary.json',info);atomic(CURRENT,info);print(json.dumps(info),flush=True);return info
 except Exception as exc:
  atomic(CURRENT,{'status':'failed','output_directory':str(out),'error':str(exc)});raise
if __name__=='__main__':
 import sys
 run(sys.argv[1] if len(sys.argv)>1 else None)
