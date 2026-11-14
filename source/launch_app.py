"""Launch only this installation; choose a free local port if another copy is running."""
import argparse,json,socket,subprocess,time,urllib.request,webbrowser
from pathlib import Path
BASE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser();p.add_argument('workflow',choices=['segmentation','time-series']);p.add_argument('--no-browser',action='store_true');args=p.parse_args()
 settings_path=BASE/'local_settings.json';settings=json.loads(settings_path.read_text())
 series=args.workflow=='time-series';key='time_series_port' if series else 'web_port';port=int(settings.get(key,8767 if series else 8766))
 identity='cell-o-vater-time-series' if series else 'vaider-radar-cell-o-vater'
 def ours(port):
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/config',timeout=1) as r:d=json.load(r)
   return d.get('application_id')==identity and d.get('application_directory')==str(BASE)
  except (OSError,ValueError):return False
 if not ours(port):
  for candidate in range(port,min(port+100,65535)):
   try:
    with socket.socket() as s:s.bind(('127.0.0.1',candidate))
    port=candidate;break
   except OSError:continue
  else:raise SystemExit('No free local port found.')
  settings[key]=port;settings_path.write_text(json.dumps(settings,indent=2))
  python=BASE/'.venv/bin/python'
  if not python.exists():raise SystemExit('Setup is incomplete. Run Install CELL-O-VATER.command from the shared package.')
  (BASE/'logs').mkdir(exist_ok=True)
  with (BASE/'logs'/f'{args.workflow}.log').open('ab') as log:
   proc=subprocess.Popen([str(python),str(BASE/('start_time_series.py' if series else 'start_web.py')),'--port',str(port)],cwd=BASE,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  for _ in range(120):
   if ours(port):break
   if proc.poll() is not None:raise SystemExit('Startup failed. See the local logs folder.')
   time.sleep(.5)
  else:raise SystemExit('Startup timed out. See the local logs folder.')
 url=f'http://127.0.0.1:{port}/'
 if not args.no_browser:webbrowser.open(url)
 print('CELL-O-VATER is running at '+url)
 print('Closing this window does not stop processing.')
if __name__=='__main__':main()
