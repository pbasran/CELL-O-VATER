"""Check runtime imports and native executables without processing any dataset."""
import os,subprocess,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent
checks=[('.venv/bin/python',['-c','import numpy,tifffile,PIL,jsonschema;import cell_analysis.server']),('.venv-cellpose/bin/python',['-c','import torch,cellpose,cv2']),('.venv-cellpose-sam/bin/python',['-c','import torch,cellpose,cv2,scipy;import cell_analysis.between_wells'])]
for executable,args in checks:
 print('Checking '+executable+' imports…',flush=True)
 subprocess.run([str(BASE/executable),*args],check=True,cwd=BASE,timeout=180)
for name in ['cpsam_v2','cyto3','nucleitorch_0']:
 if not (BASE/'models'/name).is_file():raise SystemExit('Missing model: '+name)
env=os.environ.copy();env['JAVA_HOME']=str(BASE/'runtimes/java/jdk8u504-b01-jre/Contents/Home')
subprocess.run([str(Path(env['JAVA_HOME'])/'bin/java'),'-version'],check=True,env=env,timeout=60)
subprocess.run([str(BASE/'runtimes/cellprofiler/CellProfiler.app/Contents/MacOS/cp'),'--version'],check=True,env=env,timeout=120)
print('Runtime checks passed. Validate one representative image before a full batch.')
