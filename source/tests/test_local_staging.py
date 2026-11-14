import unittest,tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
from cell_analysis.segmentation import prepare_run
class LocalStagingTests(unittest.TestCase):
 def test_original_identity_with_verified_local_pixels(self):
  import numpy as np
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);local=p/'staged';local.mkdir();(local/'A1.tif').write_bytes(b'original-bytes')
   source={'image_relative_path':'A1.tif','image_uid':'image','series_index':0,'frame_index':0,'sequence_uid':'seq'}
   m={'dataset_root':'/raw/original','dataset_uid':'dataset','_local_dataset_root':str(local),'files':[{'path':'A1.tif','sha256':hashlib.sha256(b'original-bytes').hexdigest()}]}
   options={'channel':0,'z_plane':0}
   with patch('cell_analysis.segmentation.make_plan',return_value=(options,[{'image_uid':'image','source':source}])),patch('cell_analysis.segmentation.read_plane',return_value=np.ones((8,8))) as read:
    spec=prepare_run(m,options,p/'out');self.assertEqual(spec['dataset_root'],'/raw/original');self.assertEqual(read.call_args.args[0],str(local));self.assertEqual(spec['frames'][0]['source_path'],'A1.tif')
    (local/'A1.tif').write_bytes(b'changed')
    with self.assertRaisesRegex(ValueError,'changed'):prepare_run(m,options,p/'bad')
if __name__=='__main__':unittest.main()
