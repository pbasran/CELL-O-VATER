import unittest,tempfile,json,time
from pathlib import Path
from unittest.mock import patch
import start_batch
class CrashStatusTests(unittest.TestCase):
 def status(self,state,locked=False):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'status.json';p.write_text(json.dumps(state))
   cfg={'state':str(p),'pid':1,'input':'raw','output':'processed'}
   with patch.object(start_batch,'settings',return_value=cfg),patch.object(start_batch,'busy',return_value=locked):return start_batch.status()
 def test_recycled_live_pid_does_not_hide_crash(self):
  s=self.status({'status':'running','batches':[]});self.assertEqual(s['status'],'interrupted');self.assertTrue(s['can_resume']);self.assertFalse(s['busy'])
 def test_active_lock_prevents_duplicate_resume(self):
  s=self.status({'status':'running'},True);self.assertTrue(s['busy']);self.assertFalse(s['can_resume'])
 def test_queue_startup_grace(self):
  s=self.status({'status':'queued','queued_at':time.time()});self.assertTrue(s['busy']);self.assertFalse(s['can_resume'])
 def test_abandoned_queue_recovers(self):
  s=self.status({'status':'queued','queued_at':time.time()-100});self.assertEqual(s['status'],'interrupted');self.assertTrue(s['can_resume'])
 def test_completed_run_does_not_offer_resume(self):
  self.assertFalse(self.status({'status':'complete'})['can_resume'])
if __name__=='__main__':unittest.main()
