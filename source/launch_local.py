"""Launch or reopen the local app without a chat session."""
import argparse,json,os,subprocess,time,urllib.request,webbrowser
from pathlib import Path
BASE=Path(__file__).resolve().parent
SETTINGS=json.loads((BASE/'local_settings.json').read_text()) if (BASE/'local_settings.json').exists() else {}
PORT=int(SETTINGS.get('web_port',8765))
URL=f'http://127.0.0.1:{PORT}'

def running_app():
    try:
        with urllib.request.urlopen(URL+'/api/config',timeout=2) as response:
            data=json.load(response)
            return data.get('application_id')=='vaider-radar-cell-o-vater' and data.get('application_directory')==str(BASE)
    except (OSError,ValueError):return False

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    if not running_app():
        python=BASE/'.venv/bin/python'
        if not python.exists():raise SystemExit('Local Python environment is missing. Restore the installed application before launching.')
        (BASE/'logs').mkdir(exist_ok=True)
        with (BASE/'logs/local-server.log').open('a') as log:
            process=subprocess.Popen([str(python),str(BASE/'start_web.py'),'--port',str(PORT)],cwd=BASE,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        for _ in range(60):
            if running_app():break
            if process.poll() is not None:raise SystemExit('Could not start the app. See logs/local-server.log; the configured port may already be in use.')
            time.sleep(.5)
        else:raise SystemExit('App startup timed out. See logs/local-server.log.')
        (BASE/'logs/local-server.pid').write_text(str(process.pid)+'\n')
    if not args.no_browser:webbrowser.open(URL)
    print('VAIDER-RADAR CELL-O-VATER is running at '+URL)
    print('You can close this launcher window. Processing runs locally in the background.')
if __name__=='__main__':main()
