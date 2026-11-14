import unittest,tempfile
from pathlib import Path
from cell_analysis.batch_inventory import inventory
class BatchInventoryTests(unittest.TestCase):
 def test_nested_tools_and_output(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();root=p/'raw';echo=root/'EXP001/ECHO_20261231_1000/OSCA';echo.mkdir(parents=True);(echo/'A1.tiff').touch()
   scan=root/'EXP001/EPSO_20261231_1000';scan.mkdir();(scan/'plate.jpg').touch()
   unknown=root/'unknown';unknown.mkdir();(unknown/'photo.jpg').touch()
   a=inventory(root,p/'processed');self.assertEqual(a['image_count'],1);self.assertEqual(len(a['excluded']),1);self.assertEqual(len(a['unclassified']),1)
   self.assertEqual(a['batches'][0]['results_folder'],str(p/'processed/EXP001/ECHO_20261231_1000/OSCA'))
   (root/'README.md').write_text('Source/instrument/system: ECHO microscope')
   a=inventory(root,p/'processed');self.assertEqual(len(a['excluded']),1)
   (root/'README.md').unlink()
   (echo/'README.md').write_text('Source/instrument/system: flatbed scanner')
   with self.assertRaisesRegex(ValueError,'No ECHO'):inventory(root,p/'processed')
 def test_rawdata_anchor_and_overlap(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();root=p/'0_RawData';echo=root/'EXP001/ECHO_20261231_1000';echo.mkdir(parents=True);(echo/'A1.tif').touch()
   a=inventory(root,p/'1_ProcessedData');self.assertEqual(a['batches'][0]['results_folder'],str(p/'1_ProcessedData/EXP001/ECHO_20261231_1000'))
   for output in (root,root/'processed',p):
    with self.assertRaises(ValueError):inventory(root,output)
if __name__=='__main__':unittest.main()
