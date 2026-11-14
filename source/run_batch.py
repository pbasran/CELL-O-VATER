"""Sequential unattended ECHO processing; EPSO is inventoried but not segmented."""
import argparse,copy,fcntl,json,os,re,threading,time,traceback,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import quote
# Configure only the launched process, before importing modules that choose working paths.
if __name__=='__main__':
    import hashlib
    install_id=hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:12]
    os.environ.setdefault('CELL_OVATER_WORK_ROOT',str(Path.home()/'Library/Application Support/CELL-O-VATER/work'/install_id))
    work=Path(os.environ['CELL_OVATER_WORK_ROOT'])
    os.environ.setdefault('NUMBA_CACHE_DIR',str(work/'cache/numba'))
    os.environ.setdefault('MPLCONFIGDIR',str(work/'cache/matplotlib'))
from cell_analysis import server
from cell_analysis.worker_session import WorkerSession
from cell_analysis.segmentation import SAM_PYTHON
import atexit,shutil
from cell_analysis.importer import scan_dataset
from cell_analysis.mirrored_outputs import snapshot_readmes
from cell_analysis.segmentation import validate_options
from cell_analysis.batch_inventory import inventory
from cell_analysis.batch_recovery import resumable,cleanup_scratch,sha
from cell_analysis.segmentation import MODELS

def atomic(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,default=str)+'\n');tmp.replace(path)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('destination');parser.add_argument('--state',required=True);parser.add_argument('--resume',action='store_true');parser.add_argument('--only-folder');parser.add_argument('--group-size',type=int,default=4);args=parser.parse_args()
    source=Path(args.source).resolve();target=Path(args.destination).resolve()
    if target==source or target.is_relative_to(source):raise ValueError('Outputs must be outside raw data')
    server.OUTPUT.mkdir(parents=True,exist_ok=True)
    lock_root=Path(__file__).resolve().parent/'outputs';lock_root.mkdir(exist_ok=True)
    lock=(lock_root/'unattended-experiment.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    plan=inventory(source,target)
    report_prefix=''
    if args.only_folder:
        from cell_analysis.batch_groups import grouped_plan
        plan=grouped_plan(plan,args.only_folder,args.group_size)
        report_prefix='grouped-recovery-'
    else:
        from cell_analysis.batch_groups import small_group_plan
        plan=small_group_plan(plan,args.group_size)
    state_path=Path(args.state);state_path.parent.mkdir(parents=True,exist_ok=True)
    target.mkdir(parents=True,exist_ok=True)
    prior=json.loads(state_path.read_text()) if state_path.exists() else {}
    previous_batches={}
    if prior.get('resumed_from'):
        previous_path=Path(prior['resumed_from']).resolve()
        if previous_path.is_relative_to((Path(__file__).resolve().parent/'batch_jobs').resolve()):
            previous_batches={b['folder']:b for b in json.loads(previous_path.read_text()).get('batches',[])}
    state={'status':'running','started_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'source':str(source),'output':str(target),'batches':[],'excluded':[],'notes':['Independent-image segmentation; no temporal registration or lineage inferred.','Black exterior excluded. Well names parsed only when explicit; other identifiers remain unresolved.','Folder and README dates preserved; conflicts not resolved automatically.','OSCA and K9 segmentation remain provisional pending overlay review.']}
    state['resumed_from']=prior.get('resumed_from')
    state['plan']=plan;state['excluded']=plan['excluded'];state['unclassified']=plan['unclassified']
    state['working_root']=str(server.OUTPUT)
    worker=WorkerSession(SAM_PYTHON,Path(__file__).resolve().parent/'cell_analysis/cellpose_worker.py',server.OUTPUT/('session-'+state_path.parent.name))
    atexit.register(worker.close)
    leaves=plan['batches']
    last_publish=0
    def save(force=False):
        nonlocal last_publish
        atomic(state_path,state)
        if not force and time.monotonic()-last_publish<30:return
        last_publish=time.monotonic()
        atomic(target/(report_prefix+'batch_status.json'),state)
        atomic(target/(report_prefix+'timing_report.json'),{'working_root':state['working_root'],'batches':[{'folder':b['folder'],'status':b['status'],'stages':b.get('timings',{}),'worker':b.get('worker_timings',{}),'measurements':b.get('measurement_timings',{})} for b in state['batches']]})
        lines=['# Experiment processing','',f"Status: {state['status']}",'',*['- '+n for n in state['notes']],'','| Batch | Status | Images | Cells | Report / error |','|---|---|---:|---:|---|']
        for b in state['batches']:
            link=f"[Results]({quote(Path(b['output']).relative_to(target).as_posix()+'/results.md',safe='/')})" if b['status']=='complete' else b.get('error',b.get('progress',{}).get('message',''))
            lines.append(f"| {b['folder']} | {b['status']} | {b.get('image_count','')} | {b.get('cell_count','')} | {str(link).replace('|','/')} |")
        lines+=['','Excluded flatbed/other images: '+str(len(state['excluded']))]
        (target/(report_prefix+'batch_results.md')).write_text('\n'.join(lines)+'\n')
    save()
    options=validate_options({'model':'cpsam_v2','register_fiducial':False,'exclude_black_border':True})
    model_hash=sha(MODELS/'cpsam_v2') if args.resume else None
    for item in leaves:
        if state_path.with_suffix('.stop').exists():
            state['status']='stopped';save(True);worker.close();lock.close();return
        leaf=Path(item['source']);relative=leaf.relative_to(source);b={'folder':item['folder'],'status':'importing'};state['batches'].append(b);save()
        local_source=None
        try:
            if args.resume:
                b['progress']={'message':'Verifying existing results for resume'};save()
                existing=resumable(item,options,model_hash)
                if existing:
                    b.update(existing)
                    previous=previous_batches.get(item['folder'],{})
                    for key in ['timings','worker_timings','measurement_timings']:
                        if key in previous:b[key]=previous[key]
                    save(True);continue
            stage_started=time.perf_counter();b['timings']={}
            import uuid
            local_source=server.OUTPUT/('source-'+uuid.uuid4().hex);local_source.mkdir()
            required_copy=sum((leaf/name).stat().st_size for name in item['files'])+5*1024**3
            if shutil.disk_usage(server.OUTPUT).free<required_copy:raise ValueError('Insufficient local space to stage this folder plus a 5 GB reserve')
            for image in [leaf/name for name in item['files']]:
                b['progress']={'message':'Downloading/checking '+image.name};save()
                subprocess.run([sys.executable,'-c',"import shutil,sys; shutil.copyfile(sys.argv[1],sys.argv[2])",str(image),str(local_source/image.name)],check=True,timeout=300)
            b['timings']['download_and_local_copy_seconds']=time.perf_counter()-stage_started
            stage_started=time.perf_counter()
            manifest,import_dir=scan_dataset(str(leaf),server.OUTPUT,'existing_system',exclude_paths=[str(p) for p in leaf.iterdir() if p.is_dir()]+[str(p) for p in leaf.iterdir() if p.is_file() and p.suffix.lower() in {'.tif','.tiff','.jpg','.jpeg','.png'} and p.name not in item['files']])
            manifest['_local_dataset_root']=str(local_source)
            b['timings']['import_seconds']=time.perf_counter()-stage_started
            stage_started=time.perf_counter()
            b['image_count']=len(manifest['images']);b['import_errors']=manifest.get('errors',[])
            if not manifest['images']:raise ValueError('No readable images')
            # Preserve ancestor READMEs without changing the source paths used for processing.
            ancestor=copy.deepcopy(manifest);ancestor['dataset_root']=str(source)
            for im in ancestor['images']:im['image_relative_path']=(relative/im['image_relative_path']).as_posix()
            manifest['readme_metadata']=snapshot_readmes(ancestor)
            manifest['warnings']+=state['notes']
            for im in manifest['images']:
                match=re.fullmatch(r'([A-F][1-8])(?:_(\d+))?\.(?:tiff?|jpe?g|png)',Path(im['image_relative_path']).name,re.I)
                if match:im['well_id']=match[1].upper();im['field_id']=match[2]
                im['reference_source_image_uid']=None
            (import_dir/'dataset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            b['timings']['metadata_seconds']=time.perf_counter()-stage_started
            job_id='unattended-'+str(len(state['batches']));server.JOBS[job_id]={'status':'queued'}
            b['status']='running';save()
            thread=threading.Thread(target=server.run_segmentation,args=(job_id,manifest,options,item['destination'],worker))
            thread.start()
            while thread.is_alive():
                with server.LOCK:
                    job=server.JOBS[job_id];b['progress']=copy.deepcopy(job.get('progress',{}));b['working_directory']=job.get('segmentation_output')
                save();thread.join(5)
            job=server.JOBS[job_id];seg=job.get('segmentation',{})
            if job['status']!='complete' or not seg.get('published_directory'):
                raise RuntimeError(job.get('error') or str(seg.get('measurements',{})))
            b['timings'].update(job.get('timings',{}))
            b['measurement_timings']=seg.get('measurements',{}).get('timings',{})
            timing_file=Path(b['working_directory'])/'worker_timing.json' if b.get('working_directory') else None
            if timing_file and timing_file.exists():b['worker_timings']=json.loads(timing_file.read_text())
            b.update(status='complete',cell_count=seg['object_count'],output=seg['published_directory'])
            try:b['scratch_cleanup']=cleanup_scratch(b['working_directory'],b['output'],server.OUTPUT,remove_published_copies=True)
            except Exception as cleanup_error:b['cleanup_warning']=str(cleanup_error)
            if b['import_errors']:b['status']='complete_with_import_errors'
        except Exception as exc:
            b.update(status='failed',error=str(exc));traceback.print_exc()
        finally:
            # Source copies are disposable even when preflight or processing fails.
            if local_source is not None and local_source.parent==server.OUTPUT and local_source.name.startswith('source-'):
                try:shutil.rmtree(local_source)
                except Exception as cleanup_error:b['source_cleanup_warning']=str(cleanup_error)
        save(True);print(json.dumps(b),flush=True)
        from cell_analysis.batch_groups import write_group_reports
        write_group_reports(plan,state['batches'])
    from cell_analysis.batch_groups import write_group_reports
    write_group_reports(plan,state['batches'])
    state['status']='complete' if all(b['status']=='complete' for b in state['batches']) and not state['unclassified'] else 'finished_with_exceptions'
    state['finished_at']=datetime.now(timezone.utc).isoformat();save(True);worker.close();lock.close()
if __name__=='__main__':main()
