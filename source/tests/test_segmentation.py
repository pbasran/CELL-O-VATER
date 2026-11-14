import tempfile
from pathlib import Path
import unittest
import numpy as np
import tifffile
from PIL import Image
from cell_analysis.importer import scan_dataset
from cell_analysis.segmentation import read_plane,validate_options,prepare_run,make_plan

class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'images';self.data.mkdir()
    def test_explicit_time_channel_z_selection(self):
        data=np.zeros((2,3,2,16,16),dtype='uint16')
        data[1,2,1]=99
        tifffile.imwrite(self.data/'stack.ome.tif',data,photometric='minisblack',metadata={'axes':'TCZYX'})
        image={'image_relative_path':'stack.ome.tif','series_index':0,'frame_index':100,'source_frame_index':1}
        selected=read_plane(self.data,image,2,1)
        self.assertEqual(selected.shape,(16,16));self.assertTrue((selected==99).all())
        with self.assertRaisesRegex(ValueError,'outside'):read_plane(self.data,image,3,1)
        with self.assertRaisesRegex(ValueError,'outside'):read_plane(self.data,image,0,2)
    def test_unknown_stack_axis_rejected(self):
        tifffile.imwrite(self.data/'stack.tif',np.zeros((4,16,16),dtype='uint16'),photometric='minisblack',metadata={'axes':'QYX'})
        with self.assertRaisesRegex(ValueError,'Unspecified stack axis'):
            read_plane(self.data,{'image_relative_path':'stack.tif','series_index':0,'frame_index':0},0,0)
    def test_rgb_channel_selection(self):
        pixels=np.zeros((16,16,3),dtype='uint8');pixels[:,:,1]=88
        Image.fromarray(pixels).save(self.data/'rgb.png')
        image={'image_relative_path':'rgb.png','frame_index':0}
        self.assertTrue((read_plane(self.data,image,1,0)==88).all())
        with self.assertRaises(ValueError):read_plane(self.data,image,3,0)
    def test_unchanged_source_required(self):
        path=self.data/'one.png';Image.new('L',(16,16)).save(path)
        manifest,_=scan_dataset(self.data,self.root/'imports')
        Image.new('L',(16,16),255).save(path)
        with self.assertRaisesRegex(ValueError,'changed since import'):
            prepare_run(manifest,{'model':'cyto3'},self.root/'run')
    def test_parameters_and_empty_dataset(self):
        for options in [{'model':'unknown'},{'model':'cyto3','diameter':float('nan')},{'model':'cyto3','channel':-1},{'model':'cyto3','min_size':0}]:
            with self.assertRaises(ValueError):validate_options(options)
        with self.assertRaisesRegex(ValueError,'No readable images'):make_plan({'images':[]},{'model':'cyto3'})
    def test_plan_handles_unknown_device_without_lineage_claim(self):
        Image.new('L',(16,16)).save(self.data/'one.png')
        manifest,_=scan_dataset(self.data,self.root/'imports')
        spec=prepare_run(manifest,{'model':'cyto3'},self.root/'run')
        self.assertEqual(len(spec['frames']),1)
        self.assertEqual(spec['options']['channel'],0)
        self.assertNotIn('cell_uid',spec['frames'][0])
    def test_image_limit_is_explicit_and_deterministic(self):
        for name in ['B1.png','A1.png']:Image.new('L',(16,16)).save(self.data/name)
        manifest,_=scan_dataset(self.data,self.root/'imports')
        options,plan=make_plan(manifest,{'model':'cyto3','image_limit':1})
        self.assertEqual(len(plan),1)
        self.assertEqual(plan[0]['source']['image_relative_path'],'A1.png')
    def test_local_contrast_and_refinement_limits(self):
        for value in [-1,True,16,2049,128.5]:
            with self.assertRaises(ValueError):validate_options({'model':'cyto3','tile_norm_blocksize':value})
        with self.assertRaises(ValueError):validate_options({'model':'cyto3','niter':5001})
        options=validate_options({'model':'cyto3','tile_norm_blocksize':128,'niter':1000})
        self.assertEqual(options['tile_norm_blocksize'],128)
        self.assertEqual(options['niter'],1000)

    def test_duplicate_group_is_blocking(self):
        manifest={'images':[{'image_uid':'one'}],'logical_images':[{'image_uid':'g','members':[{'source_image_uid':'one'}],'issues':['Duplicate input for this sequence/frame/channel.']}]}
        with self.assertRaisesRegex(ValueError,'grouping errors'):make_plan(manifest,{'model':'cyto3'})

if __name__=='__main__':unittest.main()
