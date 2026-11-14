import tempfile,json
from pathlib import Path
from unittest import TestCase,mock
import numpy as np
from cell_analysis import background

class BackgroundTests(TestCase):
 def test_local_mean_and_entropy(self):
  np.testing.assert_allclose(background.boxmean(np.ones((20,20)),9),1)
  np.testing.assert_allclose(background.entropy_map(np.zeros((20,20)),[0,10]),0,atol=1e-8)
  self.assertGreater(background.entropy_map(np.indices((30,30)).sum(0)%2,[0,1])[10,10],.9)
 def test_reference_validation_and_history(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);plane=np.random.default_rng(42).normal(size=(128,128));valid=np.ones_like(plane,dtype=bool);ann={'points':[],'outlines':[]};batch={'member_image_uids':['a'],'signature':{'date':'2026-10-16'},'member_count':1}
   with mock.patch.object(background,'source',return_value=(root,{'run_uid':'run'},{'image_uid':'a','source_sha256':'hash'},plane)),mock.patch.object(background.review,'arrays',return_value=(np.zeros_like(plane),valid)),mock.patch.object(background.review,'load',return_value=ann),mock.patch.object(background,'batch_members',return_value=batch):
    with self.assertRaises(ValueError):background.save(0,[0,0,64,64],False)
    with self.assertRaises(ValueError):background.save(0,[-1,0,64,64],True)
    ann['points']=[{'x':30,'y':30}]
    with self.assertRaisesRegex(ValueError,'cell mark'):background.save(0,[0,0,64,64],True)
    ann['points']=[];valid[0,0]=False
    with self.assertRaisesRegex(ValueError,'excluded'):background.save(0,[0,0,64,64],True)
    valid[0,0]=True
    first=background.save(0,[0,0,64,64],True);second=background.save(0,[0,0,64,64],True)
    self.assertNotEqual(first['profile_uid'],second['profile_uid']);self.assertEqual(len(list((root/'background-profiles').glob('*.json'))),2)
    self.assertFalse(first['automatic_suppression'])
    self.assertEqual(background.latest(0)['profile_uid'],second['profile_uid'])
    png,stats=background.preview(0);self.assertTrue(png.startswith(b'\x89PNG'));self.assertTrue(0<=stats['background_like_valid_fraction']<=1)
 def test_illumination_removes_offset_and_broad_ramp(self):
  rng=np.random.default_rng(2);texture=rng.normal(size=(180,180));valid=np.ones(texture.shape,bool)
  ramp=np.broadcast_to(np.linspace(10,90,180),(180,180))
  expected=background.illumination_residual(texture,valid)
  corrected=background.illumination_residual(texture+ramp,valid)
  np.testing.assert_allclose(corrected[40:-40,40:-40],expected[40:-40,40:-40],atol=1e-9)
  np.testing.assert_allclose(background.illumination_residual(texture+100,valid),expected,atol=1e-9)
 def test_excluded_pixels_do_not_affect_illumination(self):
  plane=np.full((128,128),50.);valid=np.ones(plane.shape,bool);valid[40:70,40:70]=False
  plane[~valid]=-1e6
  np.testing.assert_allclose(background.illumination_residual(plane,valid),0,atol=1e-8)
 def test_corrected_preview_does_not_modify_reference(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);plane=np.random.default_rng(42).normal(size=(128,128));original=plane.copy();valid=np.ones_like(plane,dtype=bool)
   with mock.patch.object(background,'source',return_value=(root,{'run_uid':'run'},{'image_uid':'a','source_sha256':'hash'},plane)),mock.patch.object(background.review,'arrays',return_value=(np.zeros_like(plane),valid)),mock.patch.object(background.review,'load',return_value={'points':[],'outlines':[]}),mock.patch.object(background,'batch_members',return_value={'member_image_uids':['a']}):
    profile=background.save(0,[0,0,64,64],True)
    path=root/'background-profiles'/(profile['profile_uid']+'.json');before=path.read_bytes()
    png,stats=background.preview(0,'illumination')
    self.assertTrue(png.startswith(b'\x89PNG'));self.assertEqual(stats['method'],'illumination')
    self.assertEqual(path.read_bytes(),before);np.testing.assert_array_equal(plane,original)
    with self.assertRaisesRegex(ValueError,'Unknown'):background.preview(0,'invalid')
 def test_texture_features_detect_edges_and_remain_finite(self):
  plane=np.zeros((100,100));plane[35:65,35:65]=20
  features=background.texture_features(plane)
  for values in features.values():
   self.assertTrue(np.isfinite(values).all())
   self.assertGreater(values[35,50],values[10,10])
  limits={name:[0,0.01] for name in features}
  matched=background.feature_match(features,limits)
  self.assertTrue(matched[10,10]);self.assertFalse(matched[35,50])
 def test_outline_overlap_includes_boundary_not_just_center(self):
  mask=np.zeros((20,20),bool);mask[4,4]=True
  ann={'outlines':[{'vertices':[[15,15],[25,15],[25,25],[15,25]]}]}
  stats=background.outline_overlap(mask,ann)
  self.assertEqual(stats['outlines_touching_blue'],1)
  self.assertGreater(stats['outlined_pixel_fraction_in_blue'],0)
  self.assertLess(stats['outlined_pixel_fraction_in_blue'],1)
 def test_combined_preview_does_not_use_annotations_to_hide_overlap(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);plane=np.random.default_rng(42).normal(size=(128,128));valid=np.ones_like(plane,dtype=bool);ann={'points':[],'outlines':[]}
   with mock.patch.object(background,'source',return_value=(root,{'run_uid':'run'},{'image_uid':'a','source_sha256':'hash'},plane)),mock.patch.object(background.review,'arrays',return_value=(np.zeros_like(plane),valid)),mock.patch.object(background.review,'load',return_value=ann),mock.patch.object(background,'batch_members',return_value={'member_image_uids':['a']}):
    background.save(0,[0,0,64,64],True)
    before,stats=background.preview(0,'combined')
    ann['points']=[{'x':80,'y':80,'confidence':'high'}]
    after,changed=background.preview(0,'combined')
    self.assertEqual(before,after);self.assertEqual(changed['marked_centers_checked'],1)
    self.assertEqual(set(stats['feature_limits']),{'local_contrast','edge_strength'})
 def test_display_bounds_preserve_holes_and_coordinates(self):
  valid=np.zeros((30,40),bool);valid[5:25,8:32]=True;valid[12:15,18:22]=False
  self.assertEqual(background.display_bounds(valid),[8,5,24,20])
  with self.assertRaisesRegex(ValueError,'no valid'):background.display_bounds(np.zeros((3,3),bool))
