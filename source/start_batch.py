"""Local-only batch launcher. No cloud/API inference or chat dependency."""
import argparse,fcntl,json,os,secrets,subprocess,sys,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from cell_analysis.batch_inventory import inventory as folder_inventory
from cell_analysis.batch_groups import small_group_plan
def inventory(source,target):return small_group_plan(folder_inventory(source,target),4)
BASE=Path(__file__).resolve().parent
SETTINGS=BASE/'batch_settings.json';TOKEN=secrets.token_urlsafe(32);GUARD=threading.Lock()
def settings():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
def write(value):
    temp=SETTINGS.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2));temp.replace(SETTINGS)
def busy():
    (BASE/'outputs').mkdir(exist_ok=True)
    with (BASE/'outputs/unattended-experiment.lock').open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
    return False
def status():
    cfg=settings();p=Path(cfg.get('state','/nonexistent'))
    state=json.loads(p.read_text()) if p.is_file() else {'status':'idle','batches':[]}
    # The OS releases this lock on exit/reboot. A recycled PID is not proof of life.
    locked=busy()
    queued_recent=state.get('status')=='queued' and time.time()-state.get('queued_at',0)<30
    if state.get('status') in {'running','queued'} and not locked and not queued_recent:
        state['status']='interrupted'
        state['error']='Processing stopped before completion. Resume verifies completed groups and retries unfinished groups.'
    state['busy']=locked or queued_recent
    state['can_resume']=not state['busy'] and state.get('status') in {'interrupted','stopped','finished_with_exceptions'} and bool(cfg.get('input') and cfg.get('output'))
    state['log']=cfg.get('log');state['can_stop']=str(p).startswith(str(BASE/'batch_jobs')+os.sep)
    queue=BASE/'next_job.json'
    if queue.exists():state['next_job']=json.loads(queue.read_text())
    return state
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,value,code=200):
        body=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/':
            body=(BASE/'web/batch.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
        elif self.path=='/api/config':self.reply({'token':TOKEN,'application_id':'cell-o-vater-batch','application_directory':str(BASE),'input':settings().get('input',''),'output':settings().get('output','')})
        elif self.path=='/api/status':
            try:self.reply(status())
            except Exception as e:self.reply({'error':str(e)},500)
        else:self.reply({'error':'Not found'},404)
    def do_POST(self):
        if self.headers.get('X-Local-Token')!=TOKEN:return self.reply({'error':'Reload the page to reconnect'},403)
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://127.0.0.1:{self.server.server_port}':return self.reply({'error':'Invalid origin'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>16384:raise ValueError('Request too large')
            data=json.loads(self.rfile.read(length))
            if self.path=='/api/preview':return self.reply(inventory(data['input'],data['output']))
            if self.path in {'/api/start','/api/resume'}:
                with GUARD:
                    if status()['busy']:raise ValueError('A batch is already running. Wait for it to finish.')
                    previous=settings()
                    if self.path=='/api/resume':
                        if not status().get('can_resume'):raise ValueError('No interrupted or unfinished run is available to resume')
                        data={'input':previous['input'],'output':previous['output']}
                    plan=inventory(data['input'],data['output'])
                    job=BASE/'batch_jobs'/uuid.uuid4().hex;job.mkdir(parents=True)
                    state=job/'status.json';state.write_text(json.dumps({'status':'queued','queued_at':time.time(),'batches':[],'plan':plan,'resumed_from':previous.get('state') if self.path=='/api/resume' else None}))
                    log=job/'run.log'
                    command=[sys.executable,'-u',str(BASE/'run_batch.py'),plan['input'],plan['output'],'--state',str(state),'--resume']
                    if Path('/usr/bin/caffeinate').exists():command=['/usr/bin/caffeinate','-i',*command]
                    with log.open('ab') as handle:p=subprocess.Popen(command,cwd=BASE,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
                    write({'input':plan['input'],'output':plan['output'],'state':str(state),'pid':p.pid,'log':str(log)})
                return self.reply({'started':True})
            if self.path=='/api/stop':
                with GUARD:
                    s=status()
                    if not s['busy'] or not s['can_stop']:raise ValueError('This run cannot be stopped from this launcher')
                    Path(settings()['state']).with_suffix('.stop').touch()
                return self.reply({'message':'Stop requested. The current batch will finish first.'})
            self.reply({'error':'Not found'},404)
        except Exception as e:self.reply({'error':str(e)},400)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8768);a=parser.parse_args()
    import os
    os.environ['CELLOVATER_BATCH_PORT']=str(a.port)
    (BASE/'logs').mkdir(exist_ok=True)
    if (BASE/'next_job.json').exists() and (BASE/'queue_next.py').exists():
        with (BASE/'logs/next-job.log').open('ab') as log:
            subprocess.Popen([sys.executable,str(BASE/'queue_next.py')],cwd=BASE,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
