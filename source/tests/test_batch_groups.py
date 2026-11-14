import unittest,tempfile
from pathlib import Path
from cell_analysis.batch_groups import grouped_plan,small_group_plan
class GroupTests(unittest.TestCase):
 def test_exact_partition_and_preserve_source(self):
  with tempfile.TemporaryDirectory() as t:
   r=Path(t);raw=r/'raw';raw.mkdir();out=r/'out'
   files=[f'A{i}.tif' for i in range(48)]
   p={'batches':[{'folder':'OSCA','source':str(raw),'destination':str(out),'results_folder':str(out),'files':files}], 'image_count':48,'excluded':[],'unclassified':[]}
   g=grouped_plan(p,'OSCA',4);self.assertEqual(len(g['batches']),12);self.assertEqual([f for b in g['batches'] for f in b['files']],files);self.assertTrue(all(b['source']==str(raw) for b in g['batches']));self.assertEqual(g,grouped_plan(p,'OSCA',4));self.assertEqual(len({b['results_folder'] for b in g['batches']}),12)
   out.mkdir();(out/'COMPLETE.json').write_text('{}')
   with self.assertRaises(ValueError):grouped_plan(p,'OSCA',4)
 def test_default_preserves_completed_folders_and_splits_others(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);out=root/'done';out.mkdir();(out/'COMPLETE.json').write_text('{}')
   rows=[{'folder':name,'source':str(root/'raw'/name),'destination':str(root/name),'results_folder':str(root/name),'files':[f'{i}.tif' for i in range(9)]} for name in ['done','new']]
   plan={'batches':rows,'image_count':18,'excluded':[],'unclassified':[]}
   result=small_group_plan(plan)
   self.assertEqual(result['batches'][0],rows[0]);self.assertEqual([len(b['files']) for b in result['batches'][1:]],[4,4,1])
if __name__=='__main__':unittest.main()
