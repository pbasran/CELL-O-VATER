import unittest,tempfile
from pathlib import Path
import numpy as np
import tifffile
from cell_analysis.between_wells import calculate,rank_comparison

class BetweenTests(unittest.TestCase):
    def test_known_kruskal_and_ties(self):
        h,p,pairs=rank_comparison({'A1':[6.3,5.4,5.7,5.2,5.0], 'A2':[6.9,7.0,6.1,7.9], 'A3':[7.2,6.9,6.1,6.5]})
        self.assertAlmostEqual(h,7.113812154696133)
        self.assertTrue(0<p<.03);self.assertEqual(len(pairs),3)
        h,p,pairs=rank_comparison({'A1':[1]*5,'A2':[1]*5})
        self.assertEqual((h,p),(0,1));self.assertEqual(pairs[0][2],1)
    def test_means_sparse_and_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);tifffile.imwrite(folder/'analysis_region.tif',np.ones((40,40),np.uint8))
            data={'feature_names':['AreaShape_Area','AreaShape_Orientation'],'images':[],'observations':[]}
            for index,well in enumerate(['A1','A2','A3']):
                data['images'].append({'image_uid':well,'well_id':well,'field_id':'0000','export_path':'/batch','time':'2026-01-01T12:00:00','folder':str(folder),'translation_x_px':0,'translation_y_px':0})
                for block in range(6 if index<2 else 1):
                    for cell in range(3):
                        data['observations'].append({'image_uid':well,'x_reference_px':(block%4)*10+2+cell,'y_reference_px':(block//4)*10+2,'AreaShape_Area':100*index+block+cell,'AreaShape_Orientation':0})
            result=calculate(data)
            self.assertEqual(result['pair_family'],6)
            self.assertEqual(result['global_family'],2)
            self.assertEqual(result['global'][0]['eligible_wells'],2)
            self.assertIsNone(result['global'][1]['p'])
            self.assertAlmostEqual(result['wells'][0]['mean'],3.5)
            self.assertFalse(result['wells'][2]['eligible'])
            pair=result['pairs'][0]
            self.assertAlmostEqual(pair['adjusted_p'],min(1,6*pair['p']))
            self.assertEqual(pair['median_difference_b_minus_a'],100)
            self.assertGreaterEqual(result['global'][0]['q'],result['global'][0]['p'])

if __name__=='__main__':unittest.main()
