"""Real PowerShell launcher flow with isolated process/network doubles."""
import json,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class LauncherTests(unittest.TestCase):
 def scenario(self,name):
  with tempfile.TemporaryDirectory(prefix='trial-launcher-') as temp:
   project=Path(temp);(project/'tools').mkdir()
   shutil.copy2(ROOT/'tools/start_public_test.ps1',project/'tools/start_public_test.ps1')
   shutil.copy2(ROOT/'tools/stop_public_test.ps1',project/'tools/stop_public_test.ps1')
   run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tests/launcher_fixture.ps1'),'-Project',str(project),'-Scenario',name],capture_output=True,timeout=30)
   calls=json.loads((project/'calls.json').read_text(encoding='utf-8-sig')) if (project/'calls.json').exists() else []
   state=json.loads((project/'.public-test/processes.json').read_text(encoding='utf-8-sig'))
   return run.returncode,calls,state,run.stdout.decode(errors='replace')
 def test_healthy_saved_url_wins_over_stale_shared_log(self):
  code,calls,state,output=self.scenario('healthy');self.assertEqual(code,0,output)
  self.assertEqual(state['public_url'],'https://saved-current.trycloudflare.com')
  self.assertFalse(any(c['kind'].startswith('start') or c['kind']=='stop' for c in calls))
  self.assertFalse(any('wrong-shared' in str(c['value']) for c in calls))
 def test_three_failed_checks_rebuild_tunnel_without_restarting_ready_app(self):
  code,calls,state,output=self.scenario('recover');self.assertEqual(code,0,output)
  self.assertEqual(state['public_url'],'https://fresh-current.trycloudflare.com')
  self.assertEqual(sum(c['kind']=='start-server' for c in calls),1)
  self.assertEqual(sum(c['kind']=='start-tunnel' for c in calls),1)
  self.assertEqual([c['value'] for c in calls if c['kind']=='stop'],[1001,1002])
  self.assertEqual(sum(c['kind']=='probe' and 'saved-current' in c['value'] for c in calls),3)
  self.assertIn('tunnel-',state['tunnel_log']);self.assertFalse(state['tunnel_log'].endswith('tunnel.err.log'))
 def test_unknown_local_port_is_never_exposed(self):
  code,calls,state,output=self.scenario('blocked-port');self.assertEqual(code,1)
  self.assertFalse(any(c['kind'].startswith('start') for c in calls))
  self.assertEqual([c['value'] for c in calls if c['kind']=='stop'],[1001,1002])
  self.assertNotIn('public_url',state)
 def test_stop_uses_the_same_lock_and_retains_saved_state(self):
  code,calls,state,output=self.scenario('stop');self.assertEqual(code,0,output)
  self.assertEqual([c['value'] for c in calls if c['kind']=='stop'],[1002,1001])
  self.assertNotIn('public_url',state);self.assertEqual(state['server_pid'],1001)

if __name__=='__main__':unittest.main(verbosity=2)
