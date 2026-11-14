"""One Cellpose process and model cache for sequential batches."""
import json,subprocess,time,os
from pathlib import Path
class WorkerSession:
 def __init__(self,python,script,root):
  self.python=python;self.script=script;self.root=Path(root);self.process=None;self.log=None
 def run(self,spec,progress):
  if self.process is None or self.process.poll() is not None:
   if self.log:self.log.close()
   self.root.mkdir(parents=True,exist_ok=True);self.log=(self.root/'persistent-worker.log').open('ab')
   self.process=subprocess.Popen([str(self.python),str(self.script),'--serve'],stdin=subprocess.PIPE,stdout=self.log,stderr=self.log,text=True,env=os.environ.copy())
  out=Path(spec).parent;done=out/'worker_done.json'
  self.process.stdin.write(json.dumps(str(spec))+'\n');self.process.stdin.flush()
  while not done.exists():
   if self.process.poll() is not None:raise RuntimeError('Persistent Cellpose worker exited; see '+str(self.root/'persistent-worker.log'))
   p=out/'progress.json'
   if p.exists():
    try:progress(**json.loads(p.read_text()))
    except (OSError,ValueError):pass
   time.sleep(.3)
  result=json.loads(done.read_text())
  if result['status']!='complete':raise RuntimeError(result['error'])
 def close(self):
  if self.process and self.process.poll() is None:
   self.process.stdin.close()
   try:self.process.wait(timeout=30)
   except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=10)
  if self.log:self.log.close()
