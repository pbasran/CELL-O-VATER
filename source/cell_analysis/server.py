"""Loopback-only web interface. Start with python -m cell_analysis.server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import tempfile
import threading
from urllib.parse import urlsplit, parse_qs
import uuid

from .output_delivery import output_root, publish_run, check_working_space
from .importer import scan_dataset
from .profiles import BASE, load_profiles
from .segmentation import PYTHON, SAM_PYTHON, MODELS, prepare_run, validate_options, make_plan

JOBS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)
TOKEN = secrets.token_urlsafe(32)
from .working_storage import WORK_ROOT
OUTPUT = WORK_ROOT
RESTORED_JOB_ID = None


def run_import(job_id, path, profile, segmentation_options=None, processed_root=None):
    with LOCK:
        JOBS[job_id]['status']='running'
        JOBS[job_id].setdefault('started_at',time.time())
        JOBS[job_id]['progress']={'stage':'importing','message':'Reading images and metadata','completed':0,'total':0}
    try:
        manifest, destination=scan_dataset(path,OUTPUT,profile,exclude_paths=[processed_root] if processed_root else [])
        from .mirrored_outputs import snapshot_readmes
        manifest['readme_metadata']=snapshot_readmes(manifest)
        (destination/'dataset_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        with LOCK:
            JOBS[job_id].update(manifest=manifest,output=str(destination))
        if segmentation_options is not None:
            run_segmentation(job_id,manifest,segmentation_options,processed_root)
        else:
            with LOCK:JOBS[job_id]['status']='complete'
    except Exception as exc:
        with LOCK:
            JOBS[job_id].update(status='failed',error=str(exc))


def run_segmentation(job_id,manifest,options,processed_root=None,worker_session=None):
    timings={};stage_started=time.perf_counter()
    destination=OUTPUT/('segmentation-'+uuid.uuid4().hex)
    awake=None
    def progress(**values):
        with LOCK:
            JOBS[job_id].setdefault('started_at',time.time())
            JOBS[job_id].update(status='running',progress=values)
    try:
        if Path('/usr/bin/caffeinate').exists():
            awake=subprocess.Popen(['/usr/bin/caffeinate','-i'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        delivery=output_root(manifest['dataset_root'],processed_root)
        delivery.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=delivery) as probe:probe.write(b'output access check')
        runtime=SAM_PYTHON if options.get('model')=='cpsam_v2' else PYTHON
        if not runtime.is_file():raise ValueError('Selected Cellpose environment is not installed')
        _,plan=make_plan(manifest,options)
        OUTPUT.mkdir(parents=True,exist_ok=True)
        check_working_space(plan,OUTPUT,delivery)
        progress(stage='preparing',completed=0,total=0,message='Preparing image planes')
        spec=prepare_run(manifest,options,destination,progress)
        timings['prepare_seconds']=time.perf_counter()-stage_started
        stage_started=time.perf_counter()
        progress(stage='loading_runtime',completed=0,total=len(spec['frames']),message='Loading Cellpose runtime')
        with LOCK:JOBS[job_id]['segmentation_output']=str(destination)
        environment=dict(os.environ)
        environment['NUMBA_CACHE_DIR']=str(BASE/'.cache/numba')
        environment['MPLCONFIGDIR']=str(BASE/'.cache/matplotlib')
        environment['CELLPOSE_LOCAL_MODELS_PATH']=str(MODELS)
        if worker_session is not None:
            worker_session.run(destination/'job_spec.json',progress)
        else:
            with (destination/'worker.log').open('w') as log:
                process=subprocess.Popen([str(runtime),str(BASE/'cell_analysis/cellpose_worker.py'),str(destination/'job_spec.json')],stdout=log,stderr=log,env=environment)
                while process.poll() is None:
                    path=destination/'progress.json'
                    if path.exists():
                        try:progress(**json.loads(path.read_text()))
                        except (ValueError,OSError):pass
                    time.sleep(.3)
                if process.returncode:
                    failure=destination/'failure.json'
                    message=json.loads(failure.read_text())['error'] if failure.exists() else 'Cellpose worker failed; see worker.log in the run folder'
                    raise RuntimeError(message)
        timings['worker_seconds']=time.perf_counter()-stage_started
        stage_started=time.perf_counter()
        result=json.loads((destination/'segmentation_manifest.json').read_text())
        if options.get('model')=='cpsam_v2':
            progress(stage='measuring',completed=len(result['images']),total=len(result['images']),message='Running CellProfiler measurements')
            with (destination/'measurements.log').open('w') as log:
                measured=subprocess.run([str(SAM_PYTHON),'-m','cell_analysis.measurements',str(destination)],cwd=BASE,stdout=log,stderr=log)
            from .measurements import CURRENT
            result['measurements']=json.loads(CURRENT.read_text()) if CURRENT.exists() else {'status':'failed','error':'No measurement status produced'}
            result['measurement_status']='complete' if measured.returncode==0 else 'failed; segmentation retained'
            (destination/'segmentation_manifest.json').write_text(json.dumps(result,indent=2))
        timings['cellprofiler_seconds']=time.perf_counter()-stage_started
        stage_started=time.perf_counter()
        if result.get('measurement_status')=='complete':
            progress(stage='saving',completed=len(result['images']),total=len(result['images']),message='Saving masks and cell table')
            published=publish_run(destination,result['measurements']['output_directory'],output_root(manifest['dataset_root'],processed_root),manifest['dataset_root'])
            result['published_directory']=published
            result['measurements']['published_directory']=published
            result['measurements']['published_layout']='mirrored_v1'
            from .measurements import atomic
            atomic(CURRENT,result['measurements'])
            (destination/'segmentation_manifest.json').write_text(json.dumps(result,indent=2))
        timings['publish_seconds']=time.perf_counter()-stage_started
        with LOCK:JOBS[job_id]['timings']=timings
        with LOCK:JOBS[job_id].update(status='complete',segmentation=result,progress={'stage':'complete','completed':len(result['images']),'total':len(result['images']),'message':'Segmentation complete'})
    except Exception as exc:
        with LOCK:JOBS[job_id].update(status='failed',error=str(exc))
    finally:
        if destination.exists():(destination/'stage_timing.json').write_text(json.dumps(timings,indent=2))
        if awake is not None:
            awake.terminate()
            awake.wait()


def preview(manifest,index):
    import numpy as np
    from PIL import Image
    image=manifest['images'][index]
    root=Path(manifest['dataset_root']).resolve()
    path=(root/image['image_relative_path']).resolve()
    if not path.is_relative_to(root):raise ValueError('Image is outside the dataset')
    if path.suffix.lower() in {'.tif','.tiff'}:
        import tifffile
        with tifffile.TiffFile(path) as tif:
            series=tif.series[image['series_index']]
            first=series.pages[0]
            if np.prod(first.shape)>64_000_000:raise ValueError('Preview plane exceeds 64 million samples')
            leading=series.axes[:-len(first.axes)] if first.axes else series.axes
            shape=series.shape[:len(leading)]
            index_page=0
            if 'T' in leading:
                t=leading.index('T')
                index_page=image.get('source_frame_index',image['frame_index'])*int(np.prod(shape[t+1:]))
            elif image.get('source_frame_index',image['frame_index'])!=0:
                raise ValueError('Preview layout requires a device-specific reader')
            array=series.pages[index_page].asarray()
        if array.ndim>2 and array.shape[-1] not in (3,4):
            while array.ndim>2:array=array[0]
        array=np.nan_to_num(array.astype(np.float32))
        lo,hi=np.percentile(array,[1,99])
        if hi<=lo:lo,hi=float(array.min()),float(array.max())
        array=np.uint8(np.clip((array-lo)/max(hi-lo,1)*255,0,255))
        im=Image.fromarray(array)
    else:
        with Image.open(path) as source:
            if source.width*source.height>20_000_000:raise ValueError('Preview exceeds 20 million pixels')
            im=source.convert('RGB')
    im.thumbnail((900,650))
    data=io.BytesIO();im.save(data,format='PNG');return data.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data,kind='application/json'):
        body=json.dumps(data).encode() if kind=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        if kind=='application/zip':self.send_header('Content-Disposition','attachment; filename=segmentation-results.zip')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(body)
    def allowed(self,write=False):
        host=self.headers.get('Host','')
        if host not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:return False
        origin=self.headers.get('Origin')
        if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}:return False
        return not write or secrets.compare_digest(self.headers.get('X-Local-Token',''),TOKEN)
    def do_GET(self):
        if not self.allowed():return self.send(403,{'error':'Local access only'})
        request=urlsplit(self.path);route=request.path
        try:
            if route.startswith('/api/measurements'):
                from .measurements import CURRENT
                if not CURRENT.exists():return self.send(200,{'status':'not_started'})
                info=json.loads(CURRENT.read_text())
                mirrored=info.get('published_layout')=='mirrored_v1'
                folder=Path(info['published_directory'] if mirrored else info['output_directory']).resolve()
                if not mirrored and not folder.is_relative_to((BASE/'outputs').resolve()):raise ValueError('Invalid output directory')
                if route=='/api/measurements':
                    if info['status']=='complete':
                        info['cells']=json.loads((folder/('cells_all_images.json' if mirrored else 'cells.json')).read_text())
                    return self.send(200,info)
                names={'/api/measurements/cells.csv':('cells_all_images.csv' if mirrored else 'cells.csv','text/csv'),'/api/measurements/cells.json':('cells_all_images.json' if mirrored else 'cells.json','application/octet-stream'),'/api/measurements/pipeline':('measurements.cppipe','application/octet-stream'),'/api/measurements/report':('results.md','text/plain; charset=utf-8')}
                if route not in names or info['status']!='complete':return self.send(404,{'error':'Measurement output unavailable'})
                name,kind=names[route]
                if not (folder/name).is_file():return self.send(404,{'error':'Output not present in this older run'})
                return self.send(200,(folder/name).read_bytes(),kind)
            if route in {'/api/background','/api/background/preview','/api/background/image'}:
                from . import background
                index=int(parse_qs(request.query).get('index',['0'])[0])
                if route.endswith('/image'):
                    return self.send(200,background.display_image(index),'image/png')
                if route.endswith('/preview'):
                    import base64
                    png,stats=background.preview(index,parse_qs(request.query).get('method',['raw'])[0])
                    return self.send(200,{'png':base64.b64encode(png).decode(),'stats':stats})
                run,_,_,_=background.source(index)
                _,valid=background.review.arrays(str(run),index)
                return self.send(200,{'profile':background.latest(index),'display_bounds':background.display_bounds(valid)})
            if route in {'/api/sam-preview','/api/sam-preview/image'}:
                trial=BASE/'outputs/cellpose-sam-full'
                if route.endswith('/image'):
                    query=parse_qs(request.query);index=int(query.get('index',['0'])[0]);mode=query.get('mode',['overlay'])[0]
                    if index not in range(3) or mode not in {'image','native','overlay','marks','excluded','contours'}:raise ValueError('Invalid preview selection')
                    if mode=='contours':
                        from PIL import Image,ImageDraw
                        pic=Image.open(trial/f'{index}-overlay.png').convert('RGB');draw=ImageDraw.Draw(pic)
                        row=next(r for r in json.loads((trial/'results.json').read_text()) if r['index']==index)
                        x,y,_,_=row['display_bounds'];ann=json.loads((trial/f'annotation-{index}.json').read_text());confidence={p['id']:p['confidence'] for p in ann['points']}
                        for outline in ann['outlines']:
                            vertices=[(px-x,py-y) for px,py in outline['vertices']]
                            color=(0,210,255) if confidence.get(outline['point_id'])=='high' else (255,80,200)
                            draw.line(vertices+[vertices[0]],fill=color,width=2)
                        buf=io.BytesIO();pic.save(buf,format='PNG');return self.send(200,buf.getvalue(),'image/png')
                    return self.send(200,(trial/f'{index}-{mode}.png').read_bytes(),'image/png')
                state=json.loads((trial/'status.json').read_text());state['available']=json.loads((trial/'available.json').read_text())
                return self.send(200,state)
            if route.startswith('/api/review'):
                from . import review
                index=int(parse_qs(request.query).get('index',['0'])[0])
                run,m=review.context()
                if not 0<=index<len(m['images']):raise ValueError('Image not found')
                if route=='/api/review/image':
                    body,kind=review.image(index,parse_qs(request.query).get('overlay',['0'])[0]=='1');return self.send(200,body,kind)
                if route=='/api/review':return self.send(200,{'images':m['images'],'annotation':review.load(index),'references':json.loads((BASE/'outputs/spindle-tuning/manual_reference_counts.json').read_text())['references'] if (BASE/'outputs/spindle-tuning/manual_reference_counts.json').exists() else []})
                return self.send(404,{'error':'Not found'})
            if route=='/api/config':
                return self.send(200,{'application_directory':str(BASE),'application_id':'vaider-radar-cell-o-vater','latest_job_id':next(iter(reversed(JOBS)),None),'active_job_id':next((k for k,v in list(JOBS.items()) if v['status'] in {'queued','running'}),None),'token':TOKEN,'profiles':load_profiles(),'demo_path':str(BASE/'examples/segmentation_demo'),'restored_job_id':RESTORED_JOB_ID,'cellpose_installed':PYTHON.is_file(),'cellpose_models':['cpsam_v2','cyto3','nuclei'],'segmentation_mode':'2D CPU','local_settings':json.loads((BASE/'local_settings.json').read_text()) if (BASE/'local_settings.json').exists() else {}})
            if route.startswith('/api/jobs/'):
                job_id=route.split('/')[3]
                with LOCK:job=dict(JOBS.get(job_id,{}))
                if not job:return self.send(404,{'error':'Import not found'})
                if route.endswith('/bundle'):
                    if not job.get('segmentation'):raise ValueError('Segmentation has not completed')
                    return self.send(200,(Path(job['segmentation_output'])/'segmentation_results.zip').read_bytes(),'application/zip')
                if route.endswith('/overlay'):
                    if not job.get('segmentation'):raise ValueError('Segmentation has not completed')
                    index=int(parse_qs(request.query).get('index',['0'])[0])
                    images=job['segmentation']['images']
                    if index<0 or index>=len(images):raise ValueError('Image not found')
                    return self.send(200,(Path(job['segmentation_output'])/images[index]['overlay_relative_path']).read_bytes(),'image/png')
                if route.endswith('/preview'):
                    if not job.get('manifest'):raise ValueError('Import is not complete')
                    index=int(parse_qs(request.query).get('index',['0'])[0])
                    if index<0 or index>=len(job['manifest']['images']):raise ValueError('Image not found')
                    return self.send(200,preview(job['manifest'],index),'image/png')
                if route.endswith('/download'):
                    if not job.get('manifest'):raise ValueError('Import is not complete')
                    return self.send(200,job['manifest'])
                return self.send(200,job)
            files={'/measurements':('measurements.html','text/html; charset=utf-8'),'/measurements.js':('measurements.js','application/javascript'),'/sam-preview':('sam-preview.html','text/html; charset=utf-8'),'/sam-preview.js':('sam-preview.js','application/javascript'),'/background':('background.html','text/html; charset=utf-8'),'/background.js':('background.js','application/javascript'),'/review':('review.html','text/html; charset=utf-8'),'/review.js':('review.js','application/javascript'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css')}
            if route in files:
                name,kind=files[route];return self.send(200,(BASE/'web'/name).read_bytes(),kind)
            self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,OSError,IndexError) as exc:self.send(400,{'error':str(exc)})
    def do_POST(self):
        if not self.allowed(True):return self.send(403,{'error':'Local request token required'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=100_000:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/background':
                from . import background
                with LOCK:result=background.save(data.get('index'),data.get('rectangle'),data.get('confirmed'))
                return self.send(200,result)
            if self.path=='/api/review':
                from . import review
                index=data.get('index')
                if isinstance(index,bool) or not isinstance(index,int):raise ValueError('Invalid image index')
                with LOCK:
                    _,m=review.context()
                    if not 0<=index<len(m['images']):raise ValueError('Image not found')
                    result=review.save(index,data)
                return self.send(200,result)
            if self.path=='/api/output-layout':
                from .mirrored_outputs import layout
                return self.send(200,layout(data['path'],data.get('output_path')))
            if self.path=='/api/import':
                profile=data.get('profile','auto')
                if profile not in {'auto','celloger','existing_system'}:raise ValueError('Unknown profile')
                path=Path(data['path']).expanduser()
                if not path.is_dir():raise ValueError('Dataset folder not found or inaccessible')
                options=validate_options(data['segmentation']) if data.get('segmentation') is not None else None
                processed_root=str(output_root(path,data.get('output_path'))) if options is not None else None
                with LOCK:
                    if any(j['status'] in {'queued','running'} for j in JOBS.values()):return self.send(409,{'error':'A run is already in progress'})
                    job_id=uuid.uuid4().hex
                    JOBS[job_id]={'id':job_id,'status':'queued'}
                POOL.submit(run_import,job_id,str(path),profile,options,processed_root)
                return self.send(202,{'id':job_id})
            if self.path=='/api/segment':
                options=validate_options(data.get('options',{}))
                with LOCK:
                    parent=JOBS.get(data.get('import_id'),{})
                    if 'manifest' not in parent:raise ValueError('Import a dataset first')
                    if any(j['status'] in {'queued','running'} for j in JOBS.values()):return self.send(409,{'error':'A run is already in progress'})
                    manifest=parent['manifest']
                    make_plan(manifest,options)
                    processed_root=str(output_root(manifest['dataset_root'],data.get('output_path')))
                    job_id=uuid.uuid4().hex
                    JOBS[job_id]={'id':job_id,'status':'queued','manifest':manifest}
                POOL.submit(run_segmentation,job_id,manifest,options,processed_root)
                return self.send(202,{'id':job_id})
            if self.path=='/api/profiles':
                from jsonschema import Draft202012Validator
                schema=json.loads((BASE/'schema/imaging_profile.schema.json').read_text())
                Draft202012Validator(schema).validate(data)
                # A UI edit cannot certify validation against real device exports.
                data['validation_status']='awaiting_sample_exports'
                with LOCK:
                    if any(j['status'] in {'queued','running'} for j in JOBS.values()):return self.send(409,{'error':'Wait for the current import before changing profiles'})
                    target=BASE/'profiles'/f"{data['imaging_source']}.json"
                    with tempfile.NamedTemporaryFile(mode='w',suffix='.json',dir=target.parent,delete=False) as f:
                        json.dump(data,f,indent=2);f.write('\n');temporary=Path(f.name)
                    try:
                        load_profiles(temporary)
                        os.replace(temporary,target)
                    finally:temporary.unlink(missing_ok=True)
                return self.send(200,{'profile':data})
            self.send(404,{'error':'Not found'})
        except Exception as exc:self.send(400,{'error':str(exc)})


def main():
    global RESTORED_JOB_ID
    settings_path=BASE/'local_settings.json'
    if settings_path.exists():
        settings=json.loads(settings_path.read_text())
        saved=(BASE/settings.get('last_import','__none__')).resolve()
        if saved.is_relative_to(OUTPUT.resolve()) and saved.is_file():
            manifest=json.loads(saved.read_text())
            if manifest.get('dataset_root')==settings.get('dataset_path'):
                RESTORED_JOB_ID=uuid.uuid4().hex
                JOBS[RESTORED_JOB_ID]={'id':RESTORED_JOB_ID,'status':'complete','manifest':manifest,'output':str(saved.parent)}
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Local: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
