'use strict';
const $=id=>document.getElementById(id);
let config, currentJob, manifest, segmentation, busy=false, startedAt=null;
function activity(state,title){$('activity').dataset.state=state;$('activity-title').textContent=title;$('activity').setAttribute('aria-busy',String(state==='running'));}
setInterval(()=>{if(busy&&startedAt){const seconds=Math.floor((Date.now()-startedAt)/1000);$('activity-clock').textContent=Math.floor(seconds/60)+'m '+seconds%60+'s';}},1000);
const status=(text,error=false)=>{$('status').textContent=text;$('status').classList.toggle('error',error);if(error){const lost=text.startsWith('Cannot confirm');activity('error',lost?'Connection lost':'Stopped — needs attention');$('activity-detail').textContent=lost?'The batch may still be running. Reopen the page to reconnect.':'Processing has not completed. See the message above.';}};
async function api(path,body){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);let response;
  try{response=await fetch(path,{signal:controller.signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':config.token},body:JSON.stringify(body)})});}catch(e){throw new Error('Cannot confirm the app status. A submitted batch may still be running; reopen this page before trying again.');}finally{clearTimeout(timer);}
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed');return data;
}
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function channel(s){s=s.trim();return s===''?null:/^\d+$/.test(s)?Number(s):s;}
function list(s){return s.split(',').map(v=>v.trim()).filter(Boolean);}
function numeric(id){const value=$(id).value.trim();if(!value)return null;const n=Number(value);if(!Number.isFinite(n)||n<=0)throw new Error('Calibration and frame intervals must be positive numbers.');return n;}
function fillSettings(){
  const p=config.profiles[$('edit-profile').value];
  $('seg-channel').value=p.channels.segmentation??'';
  $('measurement-channels').value=p.channels.measurement.join(', ');
  for(const axis of ['x','y','z'])$('pixel-'+axis).value=p.calibration_um[axis]??'';
  $('interval').value=p.timing.frame_interval_s??'';
  $('pattern').value=p.grouping.filename_pattern??'';
  $('frame-base').value=p.grouping.frame_index_base;
  $('file-channels').value=p.grouping.expected_file_channels.join(', ');
  $('file-seg').value=p.channels.segmentation_file_channel??'';
  $('mappings').value=JSON.stringify(p.metadata_mappings,null,2);
  $('save-status').textContent='';
}
$('edit-profile').addEventListener('change',fillSettings);
$('save').addEventListener('click',async()=>{
  const out=$('save-status');out.classList.remove('error');
  try{
    const p=structuredClone(config.profiles[$('edit-profile').value]);
    p.channels.segmentation=channel($('seg-channel').value);
    p.channels.measurement=list($('measurement-channels').value).map(channel);
    for(const axis of ['x','y','z'])p.calibration_um[axis]=numeric('pixel-'+axis);
    p.timing.frame_interval_s=numeric('interval');
    p.grouping.filename_pattern=$('pattern').value.trim()||null;
    p.grouping.frame_index_base=Number($('frame-base').value);
    p.grouping.expected_file_channels=list($('file-channels').value);
    p.channels.segmentation_file_channel=$('file-seg').value.trim()||null;
    p.metadata_mappings=JSON.parse($('mappings').value);
    $('save').disabled=true;
    const result=await api('/api/profiles',p);config.profiles[p.imaging_source]=result.profile;
    out.textContent='Profile saved. Changes apply to the next import.';
  }catch(e){out.textContent=e.message;out.classList.add('error');}
  finally{$('save').disabled=busy;}
});
function setBusy(value){if(value&&!busy){startedAt=Date.now();activity('running','Starting…');$('activity-clock').textContent='0m 0s';$('activity-detail').textContent='Sending request to the local app…';}busy=value;for(const id of ['run','demo','save','rerun-segmentation'])$(id).disabled=value;$('rerun-segmentation').textContent=value?'Working…':'Run segmentation with current settings';$('run').textContent=value?'Working…':$('segment-on-import').checked?(Number($('cp-limit').value)===0?'Run all images':'Run limited batch'):'Import & check';}
$('import-form').addEventListener('submit',e=>{e.preventDefault();startImport();});
$('demo').addEventListener('click',()=>{$('dataset-path').value=config.demo_path;$('profile').value='auto';$('cp-limit').value=0;$('cp-register').checked=false;startImport(true);});
function segmentationOptions(){
  const read=id=>{const v=$(id).value.trim();if(!v)throw new Error('Complete the segmentation settings.');return Number(v);};
  return {tile_norm_blocksize:read('cp-tile'),niter:read('cp-niter'),model:$('cp-model').value,register_fiducial:$('cp-register').checked,channel:read('cp-channel'),z_plane:read('cp-z'),diameter:read('cp-diameter'),min_size:read('cp-min-size'),image_limit:read('cp-limit'),flow_threshold:read('cp-flow'),cellprob_threshold:read('cp-prob')};
}
$('segment-on-import').addEventListener('change',()=>setBusy(busy));
async function followJob(job){
  currentJob=job.id;activity('running','Request received');$('activity-detail').textContent='The local app accepted this run. Waiting for progress…';
  while(true){
    const result=await api('/api/jobs/'+job.id);
    if(result.started_at)startedAt=result.started_at*1000;
    if(result.status==='queued'){activity('running','Queued');status('Request accepted; waiting for processing to start.');}
    if(result.progress){const stages={importing:'Importing',preparing:'Preparing images',checking_fiducials:'Checking fiducials',loading_runtime:'Starting processing',loading_model:'Loading SAM model',segmenting:'Segmenting',measuring:'Measuring with CellProfiler',saving:'Saving results'};activity('running',stages[result.progress.stage]||'Working');$('activity-detail').textContent=(result.progress.total?result.progress.completed+' of '+result.progress.total+' images completed · ':'')+'Last status received '+new Date().toLocaleTimeString();status(result.progress.message);$('run-progress').hidden=false;if(result.progress.total){$('run-progress').max=result.progress.total;$('run-progress').value=result.progress.completed;}else $('run-progress').removeAttribute('value');}
    if(result.status==='failed'){
      if(result.manifest){manifest=result.manifest;segmentation=null;renderResults();}
      throw new Error(result.error);
    }
    if(result.status==='complete'){
      manifest=result.manifest;segmentation=result.segmentation||null;renderResults();
      activity(segmentation?'complete':'imported',segmentation?'Processing complete':'Import complete — segmentation not started');$('activity-detail').textContent=segmentation?(segmentation.published_directory?'Saved to '+segmentation.published_directory:'Check measurement status below.'):'Click Run segmentation with current settings below the import results.';
      status(segmentation?'Segmentation complete: '+segmentation.object_count+' objects across '+segmentation.images.length+' images.':manifest.summary.error_files?'Import finished with file errors.':'Images imported. Segmentation has not started.',!segmentation&&manifest.summary.error_files>0);
      $('results').scrollIntoView({behavior:'smooth',block:'start'});return;
    }
    await new Promise(resolve=>setTimeout(resolve,900));
  }
}
async function startImport(demo=false){
  if(busy)return;
  setBusy(true);status(demo?'Starting test import…':'Starting… sending your request.');
  $('results').hidden=true;$('run-progress').hidden=false;$('run-progress').removeAttribute('value');
  try{
    const options=$('segment-on-import').checked?segmentationOptions():null;
    const job=await api('/api/import',{path:$('dataset-path').value.trim(),profile:$('profile').value,segmentation:options,output_path:demo?'':$('output-path').value.trim()});
    await followJob(job);
  }catch(e){status(e.message,true);}
  finally{setBusy(false);$('run-progress').hidden=true;}
}
$('rerun-segmentation').addEventListener('click',async()=>{
  if(busy||!manifest)return;
  setBusy(true);status('Starting… requesting segmentation.');
  try{const job=await api('/api/segment',{import_id:currentJob,options:segmentationOptions(),output_path:$('output-path').value.trim()});await followJob(job);}
  catch(e){status(e.message,true);}finally{setBusy(false);$('run-progress').hidden=true;}
});

function renderResults(){
  $('results').hidden=false;$('metrics').replaceChildren();renderSegmentation();
  const metrics=[[manifest.summary.image_files,'Image files'],[manifest.summary.logical_frames,'Input frames'],[manifest.logical_images.length,'Grouped images'],[manifest.configuration_summary.logical_images_passing_profile_checks,'Passing profile checks']];
  for(const [value,label]of metrics){const box=node('div',undefined,'metric');box.append(node('strong',value),node('span',label));$('metrics').append(box);}
  const issues=new Set(manifest.warnings);
  if(manifest.series_summary)issues.add(manifest.series_summary.field_series_count+' well/field series. Matching field suffixes across dates is provisional; registration requires visual review.');
  for(const i of manifest.images){for(const message of [...(i.configuration_issues||[]),...(i.warnings||[])]){if(manifest.series_summary&&message==='Files remain separate sequences until a filename grouping rule is configured.')continue;issues.add(message);}}
  for(const group of manifest.logical_images)for(const message of group.issues)issues.add(message);
  for(const file of manifest.files)if(file.status==='error'||file.status==='unsupported')issues.add(file.path+': '+file.reason);
  for(const e of manifest.errors)issues.add(e.path+': '+e.message);
  $('issues').replaceChildren();for(const issue of issues)$('issues').append(node('li',issue));
  if(!issues.size)$('issues').append(node('li','Import checks passed. CellProfiler measurement is not connected.'));
  $('review-badge').textContent=issues.size?issues.size+' items to review':'Checks passed';
  $('files').replaceChildren();
  for(const file of manifest.files){const row=node('tr');row.append(node('td',file.path),node('td',file.status==='readable'?'Metadata readable':file.status),node('td',file.reason||'Headers checked · pixel decoding happens during analysis'));$('files').append(row);}
  $('image-select').replaceChildren();
  manifest.images.forEach((i,index)=>{const option=node('option',i.image_relative_path+' · frame '+i.frame_index);option.value=index;$('image-select').append(option);});
  $('image-select').disabled=!manifest.images.length;showPreview();
}
function showPreview(){
  const i=manifest.images[Number($('image-select').value)];$('image-info').replaceChildren();
  $('preview').hidden=true;$('preview-error').hidden=true;
  if(!i){$('preview-error').textContent='No readable images to preview.';$('preview-error').hidden=false;return;}
  $('preview-error').textContent='Preview unavailable for this image layout.';
  $('preview').onload=()=>{$('preview').hidden=false;};
  $('preview').onerror=()=>{$('preview-error').hidden=false;};
  $('preview').src='/api/jobs/'+currentJob+'/preview?index='+$('image-select').value;
  const details=[['Image source',i.imaging_source==='existing_system'?'Existing system':i.imaging_source==='celloger'?'Celloger':'Unknown'],['Dimensions',i.axes+' · '+i.shape.join(' × ')],['Device model',i.imaging_metadata.imaging_device_model||'Not recorded'],['Serial number',i.imaging_metadata.imaging_device_serial_number||'Not recorded'],['Acquired at',i.acquired_at||'Not available'],['Profile',i.profile_id||'Not selected']];
  for(const [label,value]of details){const box=node('div');box.append(node('small',label),node('span',value));$('image-info').append(box);}
}
$('image-select').addEventListener('change',showPreview);
$('download').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(manifest,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=node('a');a.href=url;a.download='dataset-import-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
(async()=>{try{config=await api('/api/config');fillSettings();$('cp-register').checked=!!config.local_settings?.register_fiducial;if(config.local_settings?.dataset_path){$('dataset-path').value=config.local_settings.dataset_path;$('profile').value=config.local_settings.imaging_profile||'auto';$('cp-limit').value=config.local_settings.initial_image_limit??0;$('cp-register').checked=!!config.local_settings.register_fiducial;}if(config.local_settings?.segmentation_options){const ids={model:'cp-model',diameter:'cp-diameter',flow_threshold:'cp-flow',cellprob_threshold:'cp-prob',tile_norm_blocksize:'cp-tile',niter:'cp-niter'};for(const [key,id]of Object.entries(ids))if(config.local_settings.segmentation_options[key]!==undefined)$(id).value=config.local_settings.segmentation_options[key];}setBusy(false);updateScope();showOutputLayout();if(config.active_job_id||(config.latest_job_id&&config.latest_job_id!==config.restored_job_id)){setBusy(true);try{await followJob({id:config.active_job_id||config.latest_job_id});}catch(e){status(e.message,true);}finally{setBusy(false);$('run-progress').hidden=true;}return;}if(config.restored_job_id){const previous=await api('/api/jobs/'+config.restored_job_id);currentJob=previous.id;manifest=previous.manifest;renderResults();}}catch(e){status('Could not connect to the local service: '+e.message,true);for(const id of ['run','demo','save','rerun-segmentation'])$(id).disabled=true;}})();

function renderSegmentation(){
  $('segmentation-results').hidden=!segmentation;
  if(!segmentation)return;
  $('segmentation-summary').textContent=segmentation.object_count+' objects · '+segmentation.images.length+' images · Cellpose '+segmentation.engine_version+' · '+segmentation.model+' · CPU · outlines require review'+(segmentation.published_directory?' · Saved to '+segmentation.published_directory:'');
  $('seg-image').replaceChildren();
  segmentation.images.forEach((image,index)=>{const option=node('option',image.source_path+' · frame '+image.frame_index+' · '+image.object_count+' objects');option.value=index;$('seg-image').append(option);});
  showSegmentation();
}
function showSegmentation(){
  const index=Number($('seg-image').value);const image=segmentation.images[index];
  $('seg-overlay').src='/api/jobs/'+currentJob+'/overlay?index='+index;
  $('seg-frame-count').textContent=image.object_count+' segmented objects. Green outlines; yellow mask labels. '+(image.registration?'Orange boundary: excluded fiducial and field edge. Coordinates aligned to the first acquisition. ':'')+'Selected channel '+segmentation.options.channel+', Z plane '+segmentation.options.z_plane+'.';
}
$('seg-image').addEventListener('change',showSegmentation);
$('download-masks').addEventListener('click',()=>{const a=node('a');a.href='/api/jobs/'+currentJob+'/bundle';a.download='segmentation-results.zip';a.click();});

$('cp-model').addEventListener('change',()=>{if($('cp-model').value==='cpsam_v2'){ $('cp-diameter').value=0;$('cp-flow').value=.4;$('cp-tile').value=0;$('cp-niter').value=0;}else if(Number($('cp-diameter').value)===0){$('cp-diameter').value=30;}});

function updateScope(){const n=Number($('cp-limit').value);$('batch-scope').textContent=n===0?'All images in the source folder and its subfolders will be processed.':'Limited run: up to '+n+' images. Set Image limit to 0 for the full dataset.';setBusy(busy);}
$('cp-limit').addEventListener('input',updateScope);

let layoutTimer,layoutRequest=0;
async function showOutputLayout(){const request=++layoutRequest,path=$('dataset-path').value.trim();if(!path)return;try{const result=await api('/api/output-layout',{path,output_path:$('output-path').value.trim()});if(request===layoutRequest)$('output-layout').textContent='Results: '+result.results_folder+' · relative to '+result.raw_root;}catch(e){if(request===layoutRequest)$('output-layout').textContent=e.message;}}
for(const id of ['dataset-path','output-path'])$(id).addEventListener('input',()=>{clearTimeout(layoutTimer);layoutTimer=setTimeout(showOutputLayout,350);});
