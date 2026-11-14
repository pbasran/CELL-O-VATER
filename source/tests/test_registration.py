import importlib.util
import unittest

@unittest.skipUnless(importlib.util.find_spec('cv2'), 'Requires isolated Cellpose runtime')
class RegistrationTests(unittest.TestCase):
    def test_known_translation_and_exclusion(self):
        import numpy as np
        import cv2
        from cell_analysis.registration import align_to_reference
        plane=np.full((800,800),180,dtype=np.float32)
        cv2.circle(plane,(400,400),55,0,-1)
        first,valid,ref=align_to_reference(plane,margin=12)
        shifted=cv2.warpAffine(plane,np.float32([[1,0,24],[0,1,-16]]),(800,800),borderValue=180)
        aligned,valid,result=align_to_reference(shifted,(ref['center_x_px'],ref['center_y_px']),margin=12)
        self.assertAlmostEqual(result['translation_x_px'],-24,delta=1)
        self.assertAlmostEqual(result['translation_y_px'],16,delta=1)
        self.assertFalse(valid[400,400])
        self.assertFalse(valid[0,400])
        self.assertLess(np.abs(aligned[100:700,100:700]-first[100:700,100:700]).mean(),1)
    def test_blank_image_requires_review(self):
        import numpy as np
        from cell_analysis.registration import align_to_reference
        with self.assertRaisesRegex(ValueError,'fiducial'):
            align_to_reference(np.ones((800,800),dtype=np.float32))
    def test_marker_survives_uneven_illumination(self):
        import numpy as np
        import cv2
        from cell_analysis.registration import locate_fiducial
        plane=np.tile(np.linspace(55,220,1000,dtype=np.float32),(800,1))
        cv2.ellipse(plane,(500,440),(110,125),0,0,360,12,-1)
        found,mask,_=locate_fiducial(plane)
        self.assertAlmostEqual(found['center_x_px'],500,delta=5)
        self.assertAlmostEqual(found['center_y_px'],440,delta=5)
        self.assertTrue(mask[440,500])
        self.assertFalse(mask[400,100])
    def test_two_similar_markers_require_review(self):
        import numpy as np
        import cv2
        from cell_analysis.registration import locate_fiducial
        plane=np.full((800,800),180,dtype=np.float32)
        for x in [320,480]:cv2.circle(plane,(x,400),40,0,-1)
        with self.assertRaisesRegex(ValueError,'Multiple'):
            locate_fiducial(plane)
    def test_marker_connected_to_edge_by_thin_strand(self):
        import numpy as np
        import cv2
        from cell_analysis.registration import locate_fiducial
        plane=np.full((800,1000),180,dtype=np.float32)
        cv2.circle(plane,(500,400),90,0,-1)
        cv2.line(plane,(500,400),(200,0),0,5)
        original=plane.copy()
        found,mask,_=locate_fiducial(plane)
        self.assertAlmostEqual(found['center_x_px'],500,delta=5)
        self.assertAlmostEqual(found['center_y_px'],400,delta=5)
        self.assertTrue(found['thin_connection_removed_for_detection'])
        self.assertTrue(mask[400,500])
        self.assertFalse(mask[40,230])
        np.testing.assert_array_equal(plane,original)
    def test_strand_alone_is_not_a_marker(self):
        import numpy as np
        import cv2
        from cell_analysis.registration import locate_fiducial
        plane=np.full((800,1000),180,dtype=np.float32)
        cv2.line(plane,(500,400),(200,0),0,5)
        with self.assertRaisesRegex(ValueError,'fiducial'):
            locate_fiducial(plane)
