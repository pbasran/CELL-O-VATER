import unittest
import importlib.util
import numpy as np
from cell_analysis.cellpose_preprocessing import prepare_grayscale

@unittest.skipUnless(importlib.util.find_spec('cellpose'), 'Requires isolated Cellpose environment')
class PreprocessingParityTests(unittest.TestCase):
    def test_training_and_inference_receive_identical_pixels(self):
        from cellpose import train, transforms
        y,x=np.mgrid[:160,:192]
        raw=(x*.3 + y*.8 + 10*np.sin(x*.2)).astype(np.float32)
        saved=raw.copy()
        for tile in [0,64,128]:
            normalized=prepare_grayscale(raw,tile)
            train_input=train._reshape_norm([normalized.copy()],channels=[0,0],normalize_params={'normalize':False})[0]
            eval_input=transforms.convert_image(normalized.copy(),channels=[0,0]).transpose(2,0,1)
            np.testing.assert_array_equal(train_input,eval_input)
            expected=transforms.normalize_img(transforms.convert_image(raw.copy(),channels=[0,0]),normalize=True,tile_norm_blocksize=tile)[...,0]
            np.testing.assert_allclose(normalized,expected)
        np.testing.assert_array_equal(raw,saved)
    def test_constant_image_is_finite(self):
        self.assertTrue(np.isfinite(prepare_grayscale(np.ones((160,160),np.float32))).all())
    def test_invalid_input_rejected(self):
        for image in [np.zeros((3,10,10)),np.full((10,10),np.nan)]:
            with self.assertRaises(ValueError):prepare_grayscale(image)
