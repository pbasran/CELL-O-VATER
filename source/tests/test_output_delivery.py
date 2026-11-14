import csv,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from cell_analysis.output_delivery import output_root,publish_run,required_working_bytes
from cell_analysis.mirrored_outputs import layout,snapshot_readmes
from cell_analysis.importer import scan_dataset

class OutputDeliveryTests(unittest.TestCase):
 def test_disk_budget_uses_spatial_axes_only(self):
  self.assertEqual(required_working_bytes([{'source':{'axes':'YXS','shape':[100,200,4]}}]),100*200*36+5*1024**3)
 def test_nested_layout_and_rejection(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();raw=root/'0_RawData';source=raw/'Study/Treatment/Plate';source.mkdir(parents=True)
   self.assertEqual(output_root(source),root/'1_ProcessedData')
   self.assertEqual(layout(source)['results_folder'],str(root/'1_ProcessedData/Study/Treatment/Plate'))
   for bad in (root,raw,source,raw/'other',source/'processed'):
    with self.assertRaises(ValueError):output_root(source,str(bad))
   with self.assertRaises(ValueError):output_root(root/'other')
   self.assertEqual(output_root(root/'other',str(root/'results')),root/'results')
 def test_import_skips_processed_tree(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source';source.mkdir();Image.new('L',(16,16)).save(source/'raw.png')
   for folder in (source/'1_ProcessedData/run',source/'custom'):
    folder.mkdir(parents=True);Image.new('L',(16,16)).save(folder/'mask.png')
   m,_=scan_dataset(source,root/'imports',exclude_paths=[source/'custom'])
   self.assertEqual([f['path'] for f in m['files']],['raw.png'])
 def fixture(self,root):
  raw=root/'0_RawData';source=raw/'Study';source.mkdir(parents=True);seg=root/'seg';meas=root/'meas';seg.mkdir();meas.mkdir();ims=[];imports=[];rows=[]
  (raw/'README.md').write_text('Cell type: OSCA\nTreatment: control\n')
  (source/'README.md').write_text('Treatment: irradiation\n| Field | Value |\n| --- | --- |\n| Operator | AB |\n')
  for i,name in enumerate(['48 hours/A1.tif','96 hours/A1.tif']):
   path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'raw')
   (seg/f'{i}.tif').write_bytes(b'mask'+bytes([i]));(seg/f'{i}.png').write_bytes(b'overlay')
   ims.append({'image_uid':str(i),'source_path':name,'mask_relative_path':f'{i}.tif','overlay_relative_path':f'{i}.png','object_count':1})
   imports.append({'image_uid':str(i),'image_relative_path':name,'imaging_metadata':{}})
   rows.append({'cell_uid':f'U-{i}','image_uid':str(i),'image_index':i,'mask_label':1,'AreaShape_Area':12})
  m={'dataset_root':str(source),'images':imports,'summary':{'image_files':2,'error_files':0}}
  m['readme_metadata']=snapshot_readmes(m)
  (seg/'import_manifest.json').write_text(json.dumps(m));(seg/'segmentation_manifest.json').write_text(json.dumps({'images':ims,'model':'cpsam_v2','options':{}}))
  (meas/'summary.json').write_text(json.dumps({'status':'complete','cell_count':2,'feature_count':1}));(meas/'cells.json').write_text(json.dumps(rows))
  return raw,source,seg,meas,root/'1_ProcessedData'
 def test_mirror_metadata_links_history_and_raw_unchanged(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();raw,source,seg,meas,target=self.fixture(root)
   before={str(p):p.read_bytes() for p in raw.rglob('*') if p.is_file()}
   result=Path(publish_run(seg,meas,target,source));self.assertEqual(result,target/'Study')
   cell=result/'48 hours/A1.tif/cells.csv';r=list(csv.DictReader(io.StringIO(cell.read_text())))[0]
   self.assertEqual(r['readme_cell_type'],'OSCA');self.assertNotIn('readme_treatment',r)
   md=json.loads((cell.parent/'metadata.json').read_text());self.assertIn('treatment',md['metadata_conflicts'])
   self.assertEqual((cell.parent/'segmentation_mask.tif').read_bytes(),b'mask\x00')
   self.assertIn('48%20hours/A1.tif/cells.csv',(result/'results.md').read_text())
   self.assertEqual(len(json.loads((result/'cells_all_images.json').read_text())),2)
   (raw/'README.md').write_text('Cell type: CHANGED AFTER IMPORT\n')
   publish_run(seg,meas,target,source)
   self.assertIn('OSCA',cell.read_text()) # imported snapshot is frozen
   self.assertTrue(list((target/'.history').rglob('COMPLETE.json')))
   self.assertEqual((raw/'Study/48 hours/A1.tif').read_bytes(),before[str(raw/'Study/48 hours/A1.tif')])
 def test_missing_old_source_is_reported_not_fabricated(self):
  with tempfile.TemporaryDirectory() as tmp:
   m={'dataset_root':str(Path(tmp)/'missing'),'images':[{'image_uid':'x','image_relative_path':'A1.tif'}]}
   result=snapshot_readmes(m)
   self.assertEqual(result['records'],{})
   self.assertTrue(result['warnings'])
 def test_failed_publish_preserves_prior_completion(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();raw,source,seg,meas,target=self.fixture(root);result=Path(publish_run(seg,meas,target,source));before=(result/'COMPLETE.json').read_bytes()
   import os
   original=os.replace
   def fail(src,dest):
    if '.partial' in str(src) and str(dest).endswith('overlay.png'):raise OSError('Test interruption')
    return original(src,dest)
   with patch('cell_analysis.mirrored_outputs.os.replace',side_effect=fail):
    with self.assertRaises(OSError):publish_run(seg,meas,target,source)
   self.assertEqual((result/'COMPLETE.json').read_bytes(),before)
   self.assertTrue((result/'48 hours/A1.tif/overlay.png').exists())
