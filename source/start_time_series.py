"""Independent local workflow; does not restart or modify the segmentation server."""
import csv,io,json,secrets,argparse,zipfile,subprocess
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from cell_analysis.time_series import discover,analyze
from cell_analysis.plate_statistics import calculate
TOKEN=secrets.token_urlsafe(32)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,data,kind='application/json'):
        body=json.dumps(data).encode() if kind=='application/json' else data
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def allowed(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin') in {None,*('http://'+h for h in hosts)}
    def do_GET(self):
        if not self.allowed():return self.send(403,{'error':'Local access only'})
        if self.path in ('/plate-statistics.js','/between-wells.js','/time-course.js'):return self.send(200,(Path(__file__).parent/'web'/self.path[1:]).read_bytes(),'application/javascript')
        if self.path=='/api/config':return self.send(200,{'token':TOKEN,'application_id':'cell-o-vater-time-series','application_directory':str(Path(__file__).resolve().parent)})
        if self.path=='/':return self.send(200,(Path(__file__).parent/'web/time-series.html').read_bytes(),'text/html; charset=utf-8')
        self.send(404,{'error':'Not found'})
    def do_POST(self):
        if not self.allowed() or not secrets.compare_digest(self.headers.get('X-Local-Token',''),TOKEN):return self.send(403,{'error':'Local access only'})
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<100000:raise ValueError('Request too large')
            d=json.loads(self.rfile.read(size))
            if self.path=='/api/discover':return self.send(200,{'exports':discover(d['root'])})
            result=analyze(d['paths'],d.get('radius',80),d.get('same_experiment') is True)
            if self.path in ('/api/between','/api/between-download'):
                worker=Path(__file__).parent/'.venv-cellpose-sam/bin/python'
                proc=subprocess.run([str(worker),'-m','cell_analysis.between_wells'],input=json.dumps({'analysis':result,'feature':d.get('feature','AreaShape_Area')}),text=True,capture_output=True,cwd=Path(__file__).parent,timeout=180)
                if proc.returncode:raise ValueError('Between-well statistics failed: '+proc.stderr[-1000:])
                comparison=json.loads(proc.stdout)
                if self.path=='/api/between':return self.send(200,comparison)
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
                    z.writestr('between_wells.json',json.dumps(comparison,indent=2))
                    for name in ['global','wells','pairs']:
                        rows=comparison[name];buf=io.StringIO()
                        if rows:
                            writer=csv.DictWriter(buf,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                        z.writestr(name+'.csv',buf.getvalue())
                    for name in ['rows','groups']:
                        rows=comparison['density_comparison'][name];buf=io.StringIO()
                        if rows:
                            writer=csv.DictWriter(buf,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                        z.writestr('seeding_density_'+name+'.csv',buf.getvalue())
                    z.writestr('methods.txt','\n'.join(comparison['notes']+comparison['density_comparison']['notes']))
                return self.send(200,stream.getvalue(),'application/zip')
            result['statistics']=calculate(result)
            if self.path=='/api/analyze':return self.send(200,result)
            if self.path=='/api/download':
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
                    z.writestr('analysis.json',json.dumps(result,indent=2))
                    rows=result['statistics']['rows'];buf=io.StringIO()
                    fields=list(dict.fromkeys(k for r in rows for k in r))
                    if rows:
                        writer=csv.DictWriter(buf,fieldnames=fields);writer.writeheader();writer.writerows(rows)
                    z.writestr('plate_statistics.csv',buf.getvalue())
                    for name in ['observations','candidates','images','intervals']:
                        rows=result[name];buf=io.StringIO()
                        if rows:
                            w=csv.DictWriter(buf,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
                        z.writestr(name+'.csv',buf.getvalue())
                    z.writestr('results.md','# Time series candidate review\n\n'+'\n'.join('- '+w for w in result['warnings']+result['statistics']['notes']))
                return self.send(200,stream.getvalue(),'application/zip')
            return self.send(404,{'error':'Not found'})
        except Exception as e:self.send(400,{'error':str(e)})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8767);a=p.parse_args()
    print(f'Time series: http://127.0.0.1:{a.port}/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
