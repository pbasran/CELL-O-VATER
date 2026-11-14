import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
import tifffile
from cell_analysis import server

class ServerTests(unittest.TestCase):
    def handler(self,host='127.0.0.1:8765',origin=None,token=None):
        handler=server.Handler.__new__(server.Handler)
        handler.server=SimpleNamespace(server_port=8765)
        handler.headers={'Host':host}
        if origin:handler.headers['Origin']=origin
        if token:handler.headers['X-Local-Token']=token
        return handler
    def test_host_origin_and_write_token(self):
        self.assertTrue(self.handler().allowed())
        self.assertFalse(self.handler(host='malicious.example:8765').allowed())
        self.assertFalse(self.handler(origin='https://example.com').allowed())
        self.assertFalse(self.handler().allowed(True))
        self.assertTrue(self.handler(token=server.TOKEN).allowed(True))
    def test_missing_folder_returns_useful_error(self):
        handler=self.handler(token=server.TOKEN)
        handler.path='/api/import'
        payload=json.dumps({'path':'/nonexistent/cell-atlas-unit-test','profile':'auto'}).encode()
        handler.headers['Content-Length']=str(len(payload));handler.rfile=io.BytesIO(payload)
        with patch.object(handler,'send') as send:
            handler.do_POST()
            self.assertEqual(send.call_args.args[0],400)
            self.assertIn('folder not found',send.call_args.args[1]['error'])
    def test_preview_selects_requested_time_and_first_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            data=np.zeros((2,2,20,20),dtype='uint16')
            data[0,0,2:6,2:6]=100
            data[1,0,12:17,12:17]=100
            data[:,1]=200
            tifffile.imwrite(root/'image.ome.tif',data,photometric='minisblack',metadata={'axes':'TCYX'})
            manifest={'dataset_root':folder,'images':[{'image_relative_path':'image.ome.tif','series_index':0,'source_frame_index':1,'frame_index':10}]}
            image=np.asarray(Image.open(io.BytesIO(server.preview(manifest,0))))
            self.assertEqual(int(image[13,13]),255)
            self.assertEqual(int(image[3,3]),0)
    def test_preview_rejects_paths_outside_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest={'dataset_root':folder,'images':[{'image_relative_path':'../outside.png'}]}
            with self.assertRaisesRegex(ValueError,'outside the dataset'):server.preview(manifest,0)

if __name__=='__main__':unittest.main()
