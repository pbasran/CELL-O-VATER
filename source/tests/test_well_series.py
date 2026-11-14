import copy
import unittest
from cell_analysis.well_series import group_well_series

class WellSeriesTests(unittest.TestCase):
    def manifest(self):
        images=[]
        for date in ['2026-10-18','2026-10-16']:
            for well in ['A1','B1']:
                images.append(dict(image_uid=date+well,image_relative_path=date+'/'+well+'_0000.tiff',frame_index=0,acquisition={'acquisition_local_time':date+'T12:00:00'},warnings=[]))
        return dict(dataset_uid='test',images=images,configuration_summary={})
    def test_chronology_and_well_isolation(self):
        m=group_well_series(self.manifest())
        self.assertEqual(m['series_summary']['field_series_count'],2)
        self.assertEqual(len({i['sequence_uid'] for i in m['images']}),2)
        self.assertEqual([g['frame_index'] for g in m['logical_images']],[0,1,0,1])
        self.assertTrue(all(i['source_frame_index']==0 for i in m['images']))
        self.assertTrue(all('2026-10-16' in i['reference_source_image_uid'] for i in m['images']))
    def test_numbered_variants_use_acquisition_time_not_suffix(self):
        m=self.manifest()
        for i,image in enumerate(m['images']):
            image['image_relative_path']=image['image_relative_path'].split('/')[-1].replace('.tiff','-'+str(4-i)+'.tiff')
        group_well_series(m)
        self.assertEqual(m['series_summary']['field_series_count'],2)
        self.assertTrue(all('2026-10-16' in i['reference_source_image_uid'] for i in m['images']))
        self.assertTrue(all(i['field_id']=='0000' for i in m['images']))

    def test_bad_filename_does_not_partly_mutate(self):
        m=self.manifest();m['images'][-1]['image_relative_path']='unknown.tiff';before=copy.deepcopy(m)
        with self.assertRaises(ValueError):group_well_series(m)
        self.assertEqual(m,before)
    def test_duplicate_acquisition_rejected(self):
        m=self.manifest();m['images'].append(copy.deepcopy(m['images'][0]));before=copy.deepcopy(m)
        with self.assertRaisesRegex(ValueError,'Duplicate'):group_well_series(m)
        self.assertEqual(m,before)
