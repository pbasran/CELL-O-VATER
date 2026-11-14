import json,csv,tempfile,unittest
from pathlib import Path
from cell_analysis.time_series import analyze,discover
class TimeSeriesTests(unittest.TestCase):
 def make(self,root,name,time,cx,x,dataset='test'):
  p=root/name;p.mkdir();ip=p/'A1.tif';ip.mkdir()
  im={'image_uid':name,'source_path':'A1.tif','well_id':'A1','field_id':'0000','acquisition_local_time':time,'registration':{'reference_center_x_px':cx,'reference_center_y_px':400}}
  (ip/'metadata.json').write_text(json.dumps({'image':im,'cell_count':1,'readme_fields':{'dataset_id':dataset}}))
  (p/'metadata.json').write_text(json.dumps({'images':[{'output_folder':'A1.tif'}]}))
  (p/'COMPLETE.json').write_text(json.dumps({'status':'complete','run_uid':name,'cell_count':1,'image_count':1}))
  with (p/'cells_all_images.csv').open('w') as f:
   w=csv.DictWriter(f,fieldnames=['image_uid','cell_uid','AreaShape_Center_X','AreaShape_Center_Y','AreaShape_Area']);w.writeheader();w.writerow(dict(image_uid=name,cell_uid=name+'-1',AreaShape_Center_X=x,AreaShape_Center_Y=400,AreaShape_Area=100))
  return str(p)
 def test_alignment_timing_and_no_assigned_identity(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);a=self.make(root,'a','2026-10-04T10:00:00',400,450);b=self.make(root,'b','2026-10-05T14:00:00',500,550)
   r=analyze([b,a]);self.assertEqual(r['intervals'][0]['elapsed_hours'],28);self.assertEqual(r['candidates'][0]['distance_px'],0);self.assertEqual(r['observations'][1]['track_uid'],'');self.assertEqual(len(discover(root)),2)
 def test_conflicting_names_and_duplicate_selection(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);a=self.make(root,'a','2026-10-04T10:00:00',400,450);b=self.make(root,'b','2026-10-05T14:00:00',400,450,'other')
   with self.assertRaisesRegex(ValueError,'README'):analyze([a,b])
   self.assertEqual(analyze([a,b],same_experiment=True)['image_count'],2)
   with self.assertRaisesRegex(ValueError,'Duplicate image'):analyze([a,a])
