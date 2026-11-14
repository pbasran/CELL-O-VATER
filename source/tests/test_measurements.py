import unittest
from cell_analysis.measurements import intensity_scale
from cell_analysis.segmentation import validate_options
class MeasurementTests(unittest.TestCase):
 def test_fixed_source_scale(self):
  self.assertEqual(intensity_scale('uint8'),255)
  self.assertEqual(intensity_scale('uint16'),65535)
  for mode in ('RGB','RGBA','L'):self.assertEqual(intensity_scale(mode),255)
  for dtype in ('float32',None,'int16'):
   with self.assertRaises(ValueError):intensity_scale(dtype)
 def test_native_sam_size(self):
  self.assertEqual(validate_options({'model':'cpsam_v2'})['diameter'],0)
  with self.assertRaises(ValueError):validate_options({'model':'cyto3','diameter':0})
