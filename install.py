"""Install the shared release locally; never share virtual environments or job state."""
import argparse,hashlib,json,os,platform,shutil,subprocess,sys,tarfile,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parent

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def check(assets):
 if sys.platform!='darwin':raise SystemExit('This release supports macOS only.')
 if int(platform.mac_ver()[0].split('.')[0])<14:raise SystemExit('This pinned runtime release requires macOS 14 or later.')
 if sys.version_info[:2]!=(3,11):raise SystemExit('Use Python 3.11. See START HERE.txt.')
 for name,expected in json.loads((BASE/'asset-checksums.json').read_text()).items():
  path=assets/name
  if not path.is_file() or sha(path)!=expected:raise SystemExit('Missing or changed runtime asset: '+name+'. Provide the verified runtime asset folder using --assets.')
 print('Release checksums verified.',flush=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--no-open',action='store_true');p.add_argument('--destination',type=Path,default=Path.home()/'Applications/CELL-O-VATER-2026.11.13');p.add_argument('--assets',type=Path,default=Path(os.environ.get('CELLOVATER_ASSETS',str(BASE/'assets'))));a=p.parse_args();a.assets=a.assets.expanduser().resolve();check(a.assets)
 if a.check:return
 dst=a.destination.expanduser().resolve()
 if dst==BASE or BASE in dst.parents:raise SystemExit('Choose a local installation folder outside the shared release.')
 marker=dst/'installation.json'
 if dst.exists() and any(dst.iterdir()) and not marker.exists():raise SystemExit('Destination is not an installation created by this setup. Choose an empty folder.')
 if marker.exists() and json.loads(marker.read_text()).get('status')=='complete':
  print('Already installed at '+str(dst)+'. Open its launchers.');return
 dst.mkdir(parents=True,exist_ok=True)
 marker.write_text(json.dumps({'status':'installing','version':'2026.11.13'}))
 shutil.copytree(BASE/'source',dst,dirs_exist_ok=True)
 if not (dst/'local_settings.json').exists():shutil.copy2(dst/'local_settings.example.json',dst/'local_settings.json')
 for name in ['logs','outputs','models','runtimes/cellprofiler','runtimes/java']:(dst/name).mkdir(parents=True,exist_ok=True)
 for model in (a.assets/'models').iterdir():
  if model.is_file():shutil.copy2(model,dst/'models'/model.name)
 # Archives are checksum-verified release assets, not user-supplied archives.
 with zipfile.ZipFile(a.assets/'CellProfiler-macOS-4.2.8.zip') as z:
  for info in z.infolist():
   target=(dst/'runtimes/cellprofiler'/info.filename).resolve()
   if not target.is_relative_to(dst/'runtimes/cellprofiler'):raise ValueError('Invalid archive path')
  # ditto preserves the application bundle's symlinks and executable permissions.
 subprocess.run(['/usr/bin/ditto','-x','-k',str(a.assets/'CellProfiler-macOS-4.2.8.zip'),str(dst/'runtimes/cellprofiler')],check=True)
 with tarfile.open(a.assets/'temurin-jre.tar.gz') as t:
  for info in t.getmembers():
   if not (dst/'runtimes/java'/info.name).resolve().is_relative_to(dst/'runtimes/java'):raise ValueError('Invalid Java archive path')
 subprocess.run(['/usr/bin/tar','-xzf',str(a.assets/'temurin-jre.tar.gz'),'-C',str(dst/'runtimes/java')],check=True)
 plans=[('.venv','requirements-core.txt'),('.venv-cellpose','requirements-cellpose-lock.txt'),('.venv-cellpose-sam','requirements-cellpose-sam-lock.txt')]
 for env,req in plans:
  print('Installing '+env+' (internet required)…',flush=True)
  subprocess.run([sys.executable,'-m','venv',str(dst/env)],check=True)
  python=dst/env/'bin/python'
  subprocess.run([str(python),'-m','pip','install','-r',str(dst/req)],check=True)
  subprocess.run([str(python),'-m','pip','check'],check=True)
 subprocess.run([str(dst/'.venv/bin/python'),str(dst/'check_installation.py')],check=True,cwd=dst)
 marker.write_text(json.dumps({'status':'complete','version':'2026.11.13','python':sys.version,'architecture':platform.machine()},indent=2))
 print('\nInstalled at '+str(dst)+'\nOpen Start CELL-O-VATER.command or Start Time Series.command there.')
 if not a.no_open:subprocess.run(['open',str(dst)],check=False)
if __name__=='__main__':main()
