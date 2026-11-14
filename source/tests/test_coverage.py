import tempfile,unittest
from pathlib import Path
import numpy as np,tifffile
from cell_analysis.coverage import measure_coverage
class CoverageTests(unittest.TestCase):
 def test_pixels_not_labels_and_excluded_region(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);tifffile.imwrite(p/'segmentation_mask.tif',np.array([[9,9,0],[9,100,100]],dtype=np.uint32));tifffile.imwrite(p/'analysis_region.tif',np.array([[1,1,1],[0,1,1]],dtype=np.uint8))
   r=measure_coverage(p);self.assertEqual(r['segmented_cell_area_px2'],4);self.assertEqual(r['valid_image_area_px2'],5);self.assertEqual(r['coverage_percent'],80)
   tifffile.imwrite(p/'segmentation_mask.tif',np.zeros((2,3),np.uint32));self.assertEqual(measure_coverage(p)['coverage_percent'],0)
 def test_missing_empty_mismatched_not_zero(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);self.assertIsNone(measure_coverage(p)['coverage_percent'])
   tifffile.imwrite(p/'segmentation_mask.tif',np.ones((2,3),np.uint32));tifffile.imwrite(p/'analysis_region.tif',np.zeros((2,3),np.uint8));self.assertIsNone(measure_coverage(p)['coverage_percent'])
   tifffile.imwrite(p/'analysis_region.tif',np.ones((3,3),np.uint8));self.assertEqual(measure_coverage(p)['coverage_status'],'unavailable')
