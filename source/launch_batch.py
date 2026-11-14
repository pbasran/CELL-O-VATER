"""Open this installation's batch launcher, choosing an unused loopback port."""
import json,socket,subprocess,time,urllib.request,webbrowser,argparse
from pathlib import Path
BASE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');a=parser.parse_args()
    def ours(port):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/config',timeout=.5) as f:d=json.load(f)
            return d.get('application_id')=='cell-o-vater-batch' and d.get('application_directory')==str(BASE)
        except (OSError,ValueError):return False
    port=None
    for candidate in range(8768,8868):
        if ours(candidate):port=candidate;break
        try:
            with socket.socket() as s:s.bind(('127.0.0.1',candidate))
            port=candidate;break
        except OSError:continue
    if port is None:raise SystemExit('No free local port')
    if not ours(port):
        (BASE/'logs').mkdir(exist_ok=True)
        with (BASE/'logs/batch-launcher.log').open('ab') as log:
            p=subprocess.Popen([str(BASE/'.venv/bin/python'),str(BASE/'start_batch.py'),'--port',str(port)],cwd=BASE,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        for _ in range(60):
            if ours(port):break
            if p.poll() is not None:raise SystemExit('Launcher failed; see logs/batch-launcher.log')
            time.sleep(.5)
        else:raise SystemExit('Launcher startup timed out')
    url=f'http://127.0.0.1:{port}/'
    if not a.no_browser:webbrowser.open(url)
    print(url)
if __name__=='__main__':main()
