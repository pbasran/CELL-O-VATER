import tempfile,unittest
from pathlib import Path
import numpy as np
import tifffile
from cell_analysis.seeding_density import calculate

class DensityTests(unittest.TestCase):
 def test_region_counts_zero_missing_and_layout(self):
  with tempfile.TemporaryDirectory() as tmp:
   mask=np.ones((10,10),np.uint8);mask[:,0]=0;tifffile.imwrite(Path(tmp)/'analysis_region.tif',mask)
   images=[dict(image_uid=w,well_id=w,field_id='0',export_path='/batch',time='2026-01-01',folder=tmp,translation_x_px=2,translation_y_px=0) for w in ['A1','A3','A5','A7']]
   images[3]['folder']=tmp+'/missing'
   cells=[dict(image_uid='A1',x_reference_px=x,y_reference_px=3) for x in [2,5,6]]
   data=dict(dataset_ids=['OSCA-78 #2.5'],images=images,observations=cells)
   r=calculate(data);self.assertTrue(r['available'])
   self.assertEqual([x['seeded_cells_per_well'] for x in r['rows']],[250,300,350,400])
   self.assertEqual(r['rows'][0]['detected_cells'],3);self.assertEqual(r['rows'][0]['cells_in_valid_region'],2)
   self.assertAlmostEqual(r['rows'][0]['density'],2/90*1e6)
   self.assertEqual(r['rows'][1]['density'],0);self.assertIsNone(r['rows'][3]['density'])
   self.assertEqual(r['groups'][0]['valid_wells'],1);self.assertEqual(r['groups'][0]['expected_wells'],12)
   data['dataset_ids']=['OSCA-78 #2.75'];self.assertFalse(calculate(data)['available'])
