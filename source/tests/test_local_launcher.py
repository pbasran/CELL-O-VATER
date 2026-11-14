import io,json,unittest
from unittest.mock import patch
import launch_local
class LocalLauncherTests(unittest.TestCase):
 def test_only_reuses_this_installation(self):
  for directory,expected in [(str(launch_local.BASE),True),('/another/install',False)]:
   body=json.dumps({'application_id':'vaider-radar-cell-o-vater','application_directory':directory}).encode()
   with patch('urllib.request.urlopen',return_value=io.BytesIO(body)):
    self.assertEqual(launch_local.running_app(),expected)
 def test_offline_server(self):
  with patch('urllib.request.urlopen',side_effect=OSError('offline')):
   self.assertFalse(launch_local.running_app())
