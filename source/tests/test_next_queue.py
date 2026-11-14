import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
import queue_next
class QueueTests(unittest.TestCase):
 def test_predecessor_blocks_launch(self):
  for status in ['running','finished_with_exceptions']:
   with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
    p=Path(d);prior=p/'prior.json';prior.write_text(json.dumps({'status':status}));q=p/'next_job.json';q.write_text(json.dumps({'status':'queued','after_state':str(prior)}))
    with patch.object(queue_next,'BASE',p),patch.object(queue_next,'QUEUE',q),patch.object(queue_next.time,'sleep',side_effect=InterruptedError),patch.object(queue_next.urllib.request,'urlopen') as request:
     with self.assertRaises(InterruptedError):queue_next.main()
     request.assert_not_called()
    self.assertEqual(json.loads(q.read_text())['status'],'queued' if status=='running' else 'waiting_for_review')
