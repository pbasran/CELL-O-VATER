import unittest,tempfile,sys,json
from pathlib import Path
from unittest.mock import patch
import run_batch
class BatchRunnerTests(unittest.TestCase):
 def test_continues_after_failed_batch_and_publishes_status(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();root=p/'raw';target=p/'processed';work=p/'work';work.mkdir()
   for name in ['ECHO_1','ECHO_2']:
    leaf=root/name;leaf.mkdir(parents=True);(leaf/'A1.tiff').write_bytes(b'test')
   state=p/'job/status.json';calls=[]
   def scan(source,output,profile,exclude_paths):
    leaf=Path(source);folder=work/leaf.name;folder.mkdir()
    return {'dataset_root':source,'images':[{'image_uid':leaf.name,'image_relative_path':'A1.tiff'}],'warnings':[],'errors':[]},folder
   def segment(job,manifest,options,destination,worker_session=None):
    calls.append(destination)
    if len(calls)==1:run_batch.server.JOBS[job]={'status':'failed','error':'test failure'}
    else:
     Path(destination).mkdir(parents=True);(Path(destination)/'cells_all_images.csv').write_text('cell_uid,area\nx,1\n')
     run_batch.server.JOBS[job]={'status':'complete','segmentation':{'published_directory':destination,'object_count':3}}
   with patch.object(run_batch.fcntl,'flock'),patch.object(sys,'argv',['run_batch.py',str(root),str(target),'--state',str(state)]),patch.object(run_batch.server,'OUTPUT',work),patch.object(run_batch,'scan_dataset',side_effect=scan),patch.object(run_batch.server,'run_segmentation',side_effect=segment):run_batch.main()
   s=json.loads(state.read_text());self.assertEqual(s['status'],'finished_with_exceptions');self.assertEqual([b['status'] for b in s['batches']],['failed','complete']);self.assertEqual(len(calls),2);self.assertTrue(all('processing_groups' in p for p in calls));self.assertEqual(list(work.glob('source-*')),[]);self.assertTrue((target/'batch_results.md').exists())
if __name__=='__main__':unittest.main()
