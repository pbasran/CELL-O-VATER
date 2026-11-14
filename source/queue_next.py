"""Persist a successor job; start only after its predecessor finishes successfully."""
import json,time,urllib.request,fcntl,os
from pathlib import Path
BASE=Path(__file__).resolve().parent
QUEUE=BASE/'next_job.json'
def save(d):
 p=QUEUE.with_suffix('.tmp');p.write_text(json.dumps(d,indent=2));p.replace(QUEUE)
def main():
 with (BASE/'next_job.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  while True:
   q=json.loads(QUEUE.read_text())
   if q['status'] not in ['queued','waiting_for_review']:return
   try:
    prior=json.loads(Path(q['after_state']).read_text())
    if prior['status']=='complete':
     cfg=json.loads((BASE/'batch_settings.json').read_text())
     # Detect a successful launch if the supervisor stopped before updating its queue.
     if cfg.get('input')==q['input'] and cfg.get('output')==q['output'] and cfg.get('state')!=q['after_state']:
      q.update(status='started',state=cfg['state']);save(q);return
     url='http://127.0.0.1:'+os.environ.get('CELLOVATER_BATCH_PORT','8768')
     s=json.load(urllib.request.urlopen(url+'/api/status',timeout=10))
     if not s['busy']:
      c=json.load(urllib.request.urlopen(url+'/api/config',timeout=10))
      if c.get('application_directory')!=str(BASE):raise ValueError('Launcher installation mismatch')
      req=urllib.request.Request(url+'/api/start',data=json.dumps({'input':q['input'],'output':q['output']}).encode(),headers={'Content-Type':'application/json','X-Local-Token':c['token']})
      json.load(urllib.request.urlopen(req,timeout=120))
      cfg=json.loads((BASE/'batch_settings.json').read_text());q.update(status='started',state=cfg['state']);save(q);return
    elif prior['status'] in ['failed','finished_with_exceptions','stopped','interrupted']:
     q.update(status='waiting_for_review',message='Previous run needs review before the next experiment starts.');save(q)
   except Exception as e:
    q['message']=str(e);save(q)
   time.sleep(15)
if __name__=='__main__':main()
