import tempfile,json
from pathlib import Path
from unittest import TestCase,mock
import numpy as np
from cell_analysis import review

class ReviewTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  m={'run_uid':'test','images':[{'image_uid':'image'}]}
  a=np.zeros((20,30),dtype='uint32');a[5:10,5:10]=7;v=np.ones_like(a,dtype=bool);v[0]=False
  for patcher in [mock.patch.object(review,'context',return_value=(self.root,m)),mock.patch.object(review,'arrays',return_value=(a,v))]:
   patcher.start();self.addCleanup(patcher.stop)
 def test_candidate_intersections_and_confidence_persist(self):
  result=review.save(0,{'revision':0,'points':[{'id':'a','x':6,'y':6,'confidence':'high'},{'id':'b','x':12,'y':0,'confidence':'low'}]})
  self.assertEqual(result['points'][0]['mask_label_at_point'],7)
  self.assertIsNone(result['points'][1]['mask_label_at_point'])
  self.assertFalse(result['points'][1]['inside_analysis_region'])
  self.assertEqual(review.load(0),result)
  with self.assertRaisesRegex(ValueError,'changed elsewhere'):review.save(0,{'revision':0,'points':[]})
  self.assertEqual(review.save(0,{'revision':1,'points':[]})['points'],[])
 def test_invalid_point_does_not_write(self):
  for p in [{'id':'a','x':float('nan'),'y':1,'confidence':'high'},{'id':'a','x':30,'y':1,'confidence':'high'},{'id':'a','x':1,'y':1,'confidence':'certain'}]:
   with self.assertRaises(ValueError):review.save(0,{'revision':0,'points':[p]})
  self.assertEqual(list(self.root.iterdir()),[])
 def test_outlines_survive_point_only_saves_and_follow_mark_deletion(self):
  point={'id':'a','x':6,'y':6,'confidence':'high'}
  outline={'point_id':'a','vertices':[[4,4],[10,4],[10,11],[4,11]]}
  first=review.save(0,{'revision':0,'points':[point],'outlines':[outline]})
  self.assertEqual(first['outlines'][0]['polygon_area_px2'],42)
  second=review.save(0,{'revision':1,'points':[point]})
  self.assertEqual(second['outlines'],first['outlines'])
  self.assertEqual(review.save(0,{'revision':2,'points':[]})['outlines'],[])
 def test_invalid_outline_preserves_saved_marks(self):
  point={'id':'a','x':6,'y':6,'confidence':'high'}
  before=review.save(0,{'revision':0,'points':[point]})
  for vertices in [[[1,1],[2,2]],[[1,1],[9,9],[1,9],[9,1]],[[1,1],[31,2],[3,3]],[[1,1],[1,1],[4,4]],[[1,1],[2,2],[3,3]]]:
   with self.assertRaises(ValueError):review.save(0,{'revision':1,'points':[point],'outlines':[{'point_id':'a','vertices':vertices}]})
   self.assertEqual(review.load(0),before)
