"""Deterministic small groups with separate, resumable publications."""
import copy,hashlib
from pathlib import Path
from .mirrored_outputs import layout

def grouped_plan(plan,folder,size):
 if size<1:raise ValueError('Group size must be positive')
 selected=[b for b in plan['batches'] if b['folder']==folder]
 if len(selected)!=1:raise ValueError('Select exactly one known input folder')
 original=selected[0]
 if (Path(original['results_folder'])/'COMPLETE.json').exists():raise ValueError('This folder already has completed results; grouping will not reprocess it')
 rows=[]
 for start in range(0,len(original['files']),size):
  b=copy.deepcopy(original);b['files']=original['files'][start:start+size]
  key=hashlib.sha256('\n'.join(b['files']).encode()).hexdigest()[:10]
  name=f'group-{start//size+1:03d}-{key}'
  b['group_root']=original['results_folder'];b['folder']=folder+'/'+name;b['destination']=str(Path(original['results_folder'])/'processing_groups'/name)
  b['results_folder']=layout(Path(b['source']),b['destination'])['results_folder'];rows.append(b)
 result=copy.deepcopy(plan);result['batches']=rows;result['image_count']=sum(len(b['files']) for b in rows);result['excluded']=[];result['unclassified']=[]
 return result

def write_group_report(plan,batches):
 """Index completed groups without pretending a partial run is complete."""
 import csv,json,os
 from urllib.parse import quote
 roots={Path(b.get('group_root',str(Path(b['results_folder']).parent.parent))) for b in plan['batches']}
 if len(roots)!=1:raise ValueError('Grouped outputs do not share one result root')
 root=roots.pop();root.mkdir(parents=True,exist_ok=True)
 done=[b for b in batches if b['status']=='complete'];complete=len(done)==len(plan['batches'])
 lines=['# Grouped image analysis','',f"Status: {'complete' if complete else 'partial'}",f"Images completed: {sum(b.get('image_count',0) for b in done)} / {plan['image_count']}",f"Segmented objects: {sum(b.get('cell_count',0) for b in done)}",'','| Group | Status | Images | Objects | Results |','|---|---|---:|---:|---|']
 for b in batches:
  link=''
  if b.get('output'):link='[Results]('+quote((Path(b['output']).relative_to(root)/'results.md').as_posix(),safe='/')+')'
  lines.append(f"| {b['folder'].split('/')[-1]} | {b['status']} | {b.get('image_count',0)} | {b.get('cell_count','')} | {link} |")
 if complete:
  rows=[];fields=[]
  for b in done:
   with (Path(b['output'])/'cells_all_images.csv').open(newline='') as f:
    reader=csv.DictReader(f)
    for key in reader.fieldnames:
     if key not in fields:fields.append(key)
    rows.extend(reader)
  tmp=root/'cells_all_images.csv.tmp'
  with tmp.open('w',newline='') as f:
   writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
  os.replace(tmp,root/'cells_all_images.csv');lines+=['','[Combined cell features](cells_all_images.csv)']
 (root/'results.md').write_text('\n'.join(lines)+'\n')
 (root/'group_summary.json').write_text(json.dumps({'status':'complete' if complete else 'partial','plan':plan,'batches':batches},indent=2))


def small_group_plan(plan,size=4):
 """Keep completed whole folders for verification; split unfinished folders."""
 result=copy.deepcopy(plan);result['batches']=[]
 for batch in plan['batches']:
  if any((Path(batch['results_folder'])/name).exists() for name in ['COMPLETE.json','run_manifest.json']):
   result['batches'].append(batch)
  else:result['batches'].extend(grouped_plan(plan,batch['folder'],size)['batches'])
 return result

def write_group_reports(plan,batches):
 for root in {b['group_root'] for b in plan['batches'] if 'group_root' in b}:
  subset=[b for b in plan['batches'] if b.get('group_root')==root]
  names={b['folder'] for b in subset}
  selected=[b for b in batches if b['folder'] in names]
  if selected:write_group_report({**plan,'batches':subset,'image_count':sum(len(b['files']) for b in subset)},selected)
