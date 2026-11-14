import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import tifffile
from PIL import Image
from cell_analysis.importer import scan_dataset, digest, empty_metadata, ome_metadata, apply_sidecar

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.data=self.base/'data';self.data.mkdir()
        self.out=self.base/'output'

    def test_excluded_files_are_not_imported(self):
        for name in ['A1.tiff','A2.tiff']:
            tifffile.imwrite(self.data/name,np.zeros((16,16),dtype='uint8'))
        manifest,_=scan_dataset(self.data,self.out,exclude_paths=[str(self.data/'A2.tiff')])
        self.assertEqual(manifest['summary']['image_files'],1)
        self.assertEqual([i['image_relative_path'] for i in manifest['images']],['A1.tiff'])

    def test_ome_time_channels_and_repeat_identity(self):
        p=self.data/'timelapse.ome.tif'
        tifffile.imwrite(p,np.zeros((3,2,16,16),dtype='uint16'),photometric='minisblack',
                         metadata={'axes':'TCYX','Channel':{'Name':['Phase','GFP']},'PhysicalSizeX':0.5})
        checksum=digest(p)
        a,_=scan_dataset(self.data,self.out)
        b,_=scan_dataset(self.data,self.out)
        self.assertEqual(a['summary']['logical_frames'],3)
        self.assertEqual(a['images'][0]['acquisition']['channels'][1]['name'],'GFP')
        self.assertEqual([i['image_uid'] for i in a['images']],[i['image_uid'] for i in b['images']])
        self.assertEqual(digest(p),checksum)
        self.assertEqual(a['images'][0]['imaging_source'],'unknown')
        self.assertIsNone(a['images'][0]['imaging_metadata']['acquisition_software_name'])

    def test_sidecar_and_profile_detection(self):
        Image.new('L',(12,12)).save(self.data/'one.png')
        (self.data/'one.json').write_text(json.dumps({'imaging_metadata':{'imaging_device_model':'Celloger example','imaging_device_serial_number':'000123'}}))
        a,_=scan_dataset(self.data,self.out)
        self.assertEqual(a['detected_profile'],'celloger')
        i=a['images'][0]
        self.assertEqual(i['imaging_metadata']['imaging_device_serial_number'],'000123')
        self.assertEqual(i['imaging_metadata_provenance']['imaging_device_model']['source'],'sidecar_metadata')
        b,_=scan_dataset(self.data,self.out,'existing_system')
        self.assertTrue(any('conflicts' in w for w in b['warnings']))

    def test_errors_unsupported_and_symlinks(self):
        (self.data/'broken.tif').write_bytes(b'not a tiff')
        (self.data/'vendor.nd2').write_bytes(b'example')
        (self.data/'linked.tif').symlink_to(self.data/'broken.tif')
        a,_=scan_dataset(self.data,self.out)
        self.assertEqual(a['summary']['image_files'],2)
        self.assertEqual(a['summary']['error_files'],1)
        self.assertEqual(a['summary']['unsupported_files'],1)

    def test_conflict_preserved_and_linked_instrument(self):
        xml='''<OME><Instrument ID="A"><Microscope Model="Other"/></Instrument>
        <Instrument ID="B"><Microscope Model="Celloger test" SerialNumber="001"/></Instrument>
        <Image ID="I"><AcquisitionDate>2026-10-20T10:00:00</AcquisitionDate><InstrumentRef ID="B"/>
        <Pixels><Plane TheT="0" DeltaT="0"/><Plane TheT="0" DeltaT="1"/></Pixels></Image></OME>'''
        m=empty_metadata();details=ome_metadata(xml,0,m,'image.tif')
        self.assertEqual(m['values']['imaging_device_model'],'Celloger test')
        self.assertNotIn('acquired_at_frame_zero',details)
        self.assertEqual(details['frame_times'],{})
        p=self.data/'image.json';p.write_text('{"imaging_device_model":"Different"}')
        apply_sidecar(p,m,self.data)
        self.assertEqual(m['values']['imaging_device_model'],'Celloger test')
        self.assertEqual(len(m['conflicts']),1)

    def test_malformed_sidecar_and_output_exclusion(self):
        Image.new('L',(12,12)).save(self.data/'one.png')
        (self.data/'one.json').write_text('{invalid')
        a,_=scan_dataset(self.data,self.data/'outputs')
        self.assertEqual(a['summary']['readable_files'],1)
        self.assertTrue(any('Sidecar' in w for w in a['images'][0]['warnings']))
        Image.new('L',(12,12)).save(self.data/'outputs'/'generated.png')
        b,_=scan_dataset(self.data,self.data/'outputs')
        self.assertEqual(b['summary']['readable_files'],1)
        with self.assertRaises(ValueError):scan_dataset(self.data,self.data)

    def test_jpeg_exif_camera_and_timestamp(self):
        exif=Image.Exif();exif[271]='Camera maker';exif[272]='Camera model';exif[42033]='00042'
        exif[36867]='2026:10:04 10:54:00';exif[36881]='-04:00'
        Image.new('RGB',(16,16)).save(self.data/'sample.jpg',exif=exif)
        result,_=scan_dataset(self.data,self.out)
        image=result['images'][0]
        self.assertEqual(image['axes'],'YXS')
        self.assertEqual(image['imaging_metadata']['camera_serial_number'],'00042')
        self.assertIsNone(image['imaging_metadata']['imaging_device_model'])
        self.assertEqual(image['acquired_at'],'2026-10-04T10:54:00-04:00')

    def test_schema_examples(self):
        from jsonschema import Draft202012Validator,FormatChecker
        root=Path(__file__).resolve().parents[1]
        schema=json.loads((root/'schema/cell_observation.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        validator=Draft202012Validator(schema,format_checker=FormatChecker())
        for line in (root/'examples/cell_observations.jsonl').read_text().splitlines():
            validator.validate(json.loads(line))

if __name__=='__main__':unittest.main()
