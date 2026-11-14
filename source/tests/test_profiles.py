import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from cell_analysis.importer import scan_dataset
from cell_analysis.profiles import load_profiles

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.data=self.base/'data';self.data.mkdir()
        self.profile=load_profiles()['existing_system']
        self.profile.update(validation_status='validated_on_representative_exports')
        self.profile['calibration_um'].update(x=.5,y=.5)
        self.profile['channels']['segmentation']=0
        self.profile['grouping']['filename_pattern']=r'(?P<sequence>well\d+)_t(?P<frame>\d+)_(?P<channel>\w+)\.png'
        self.profile['timing']['frame_interval_s']=60
        self.path=self.base/'profile.json'
    def scan(self):
        self.path.write_text(json.dumps(self.profile))
        return scan_dataset(self.data,self.base/'out','existing_system',self.path)[0]
    def image(self,name,size=(12,12)):
        Image.new('L',size).save(self.data/name)
    def test_grouping_numeric_order_and_units(self):
        for frame in [10,2,1]:self.image(f'well1_t{frame}_phase.png')
        result=self.scan();groups=result['logical_images']
        self.assertEqual([g['frame_index'] for g in groups],[1,2,10])
        self.assertEqual(len({g['sequence_uid'] for g in groups}),1)
        self.assertTrue(all(g['profile_checks_passed'] for g in groups))
        image=next(i for i in result['images'] if i['frame_index']==2)
        self.assertEqual(image['elapsed_time_s'],120)
        self.assertEqual(image['calibration_source']['x'],'user_supplied_profile')
        again=self.scan()
        self.assertEqual([g['image_uid'] for g in groups],[g['image_uid'] for g in again['logical_images']])
    def test_channel_grouping_missing_and_dimensions(self):
        self.profile['grouping']['expected_file_channels']=['phase','gfp']
        self.image('well1_t0_phase.png');self.image('well1_t0_gfp.png',(14,14));self.image('well1_t1_phase.png')
        result=self.scan()
        self.assertEqual(len(result['logical_images']),2)
        self.assertTrue(any('dimensions' in i for i in result['logical_images'][0]['issues']))
        self.assertTrue(any('Missing' in i for i in result['logical_images'][1]['issues']))
        self.assertFalse(any(g['profile_checks_passed'] for g in result['logical_images']))
    def test_vendor_mapping_preserves_serial_and_conflicts(self):
        self.image('well1_t0_phase.png')
        (self.data/'well1_t0_phase.json').write_text(json.dumps({'imaging_device_serial_number':'001','vendor':{'sn':'002','version':'3.1'}}))
        self.profile['metadata_mappings']=[{'source':'sidecar_json','path':['vendor','sn'],'field':'imaging_device_serial_number'}, {'source':'sidecar_json','path':['vendor','version'],'field':'acquisition_software_version'}]
        result=self.scan();image=result['images'][0]
        self.assertEqual(image['imaging_metadata']['imaging_device_serial_number'],'001')
        self.assertEqual(image['imaging_metadata']['acquisition_software_version'],'3.1')
        self.assertEqual(image['imaging_metadata_provenance']['acquisition_software_version']['metadata_key'],'vendor.version')
        self.assertEqual(len(image['metadata_conflicts']),1)
        self.assertFalse(result['logical_images'][0]['profile_checks_passed'])
    def test_invalid_profile_rejected_before_output(self):
        self.profile['calibration_um']['x']=-1
        with self.assertRaises(Exception):self.scan()
        self.assertFalse((self.base/'out').exists())
        self.profile['calibration_um']['x']=1
        self.profile['grouping']['filename_pattern']='.*'
        with self.assertRaisesRegex(ValueError,'named sequence and frame'):self.scan()
    def test_duplicate_frame_channel(self):
        self.image('well1_t01_phase.png');self.image('well1_t1_phase.png')
        result=self.scan()
        self.assertTrue(any('Duplicate' in i for i in result['logical_images'][0]['issues']))
    def test_complete_channel_group_selects_segmentation_file(self):
        self.profile['grouping']['expected_file_channels']=['phase','gfp']
        self.profile['channels']['segmentation_file_channel']='phase'
        self.image('well1_t0_phase.png');self.image('well1_t0_gfp.png')
        result=self.scan();group=result['logical_images'][0]
        phase=next(i for i in result['images'] if 'phase' in i['image_relative_path'])
        self.assertTrue(group['profile_checks_passed'])
        self.assertEqual(group['segmentation_source_image_uid'],phase['image_uid'])
    def test_embedded_calibration_overrides_fallback(self):
        import numpy as np
        import tifffile
        self.profile['grouping']['filename_pattern']=None
        tifffile.imwrite(self.data/'image.ome.tif',np.zeros((16,16),dtype='uint16'),
                         metadata={'axes':'YX','PhysicalSizeX':200,'PhysicalSizeXUnit':'nm','PhysicalSizeY':200,'PhysicalSizeYUnit':'nm'})
        result=self.scan();image=result['images'][0]
        self.assertAlmostEqual(image['pixel_size_um']['x'],.2)
        self.assertEqual(image['calibration_source']['x'],'embedded_metadata')
    def test_default_profiles_remain_unconfigured(self):
        for p in load_profiles().values():
            self.assertEqual(p['validation_status'],'awaiting_sample_exports')
            self.assertEqual(p['channels']['segmentation'],0 if p['imaging_source']=='existing_system' else None)
            self.assertIsNone(p['calibration_um']['x'])

if __name__=='__main__':unittest.main()
