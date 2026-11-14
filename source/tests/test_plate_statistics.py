import unittest
from cell_analysis.plate_statistics import sign_flip,adjust_by
class PlateStatsTests(unittest.TestCase):
 def test_exact_sign_flips(self):
  self.assertEqual(sign_flip([1]*6),2/64)
  self.assertEqual(sign_flip([0]*6),1)
  self.assertEqual(sign_flip([1,-1]*3),1)
 def test_correction(self):
  q=adjust_by([.01,.04,.03]);expected=[.055,.0733333333333,.0733333333333]
  for a,b in zip(q,expected):self.assertAlmostEqual(a,b)
  self.assertEqual(adjust_by([1,1]),[1,1])
 def test_common_region_and_sparse_blocks(self):
  import tempfile
  from pathlib import Path
  import numpy as np,tifffile
  from cell_analysis.plate_statistics import calculate
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);ims=[];cells=[]
   for index in range(2):
    folder=root/str(index);folder.mkdir();mask=np.ones((400,400),np.uint8);mask[:100,:100]=0
    tifffile.imwrite(folder/'analysis_region.tif',mask)
    ims.append({'image_uid':str(index),'well_id':'A1','field_id':'0000','time':f'2026-10-0{index+1}T10:00:00','folder':str(folder),'translation_x_px':0,'translation_y_px':0})
    for block in range(8):
     for i in range(3):cells.append({'image_uid':str(index),'x_reference_px':(block%4)*100+50+i,'y_reference_px':(block//4)*100+50,'AreaShape_Area':10+index})
   r=calculate({'feature_names':['AreaShape_Area'],'images':ims,'observations':cells})['rows'][0]
   self.assertEqual(r['paired_blocks'],7);self.assertEqual(r['n_cells_t1'],21);self.assertEqual(r['effect'],1);self.assertEqual(r['p'],2/128)
   cells=[c for c in cells if c['y_reference_px']<100]
   r=calculate({'feature_names':['AreaShape_Area'],'images':ims,'observations':cells})['rows'][0]
   self.assertEqual(r['status'],'insufficient');self.assertIsNone(r['p'])
