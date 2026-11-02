"""Real PowerShell launcher flow with isolated process/network doubles."""
import json,shutil,subprocess,tempfile,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class LauncherTests(unittest.TestCase):
 def scenario(self,name,shell='powershell.exe'):
  with tempfile.TemporaryDirectory(prefix='trial-launcher-') as temp:
   project=Path(temp);(project/'tools').mkdir()
   shutil.copy2(ROOT/'tools/start_public_test.ps1',project/'tools/start_public_test.ps1')
   shutil.copy2(ROOT/'tools/stop_public_test.ps1',project/'tools/stop_public_test.ps1')
   # Both copied scripts keep a shared lock, isolated from real launches and other tests.
   mutex='Local\\AIInterviewPublicTrialStartupFixture'+uuid.uuid4().hex
   for filename in ('start_public_test.ps1','stop_public_test.ps1'):
    path=project/'tools'/filename
    path.write_text(path.read_text(encoding='utf-8-sig').replace('Local\\AIInterviewPublicTrialStartup',mutex),encoding='utf-8-sig')
   run=subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tests/launcher_fixture.ps1'),'-Project',str(project),'-Scenario',name],capture_output=True,timeout=30)
   calls=json.loads((project/'calls.json').read_text(encoding='utf-8-sig')) if (project/'calls.json').exists() else []
   state=json.loads((project/'.public-test/processes.json').read_text(encoding='utf-8-sig'))
   probe_log=project/'.public-test/connectivity.jsonl'
   self.probes=[json.loads(line) for line in probe_log.read_text(encoding='utf-8-sig').splitlines()] if probe_log.exists() else []
   self.assertNotIn('fixture secret',probe_log.read_text(encoding='utf-8-sig') if probe_log.exists() else '')
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
 def test_new_domain_can_become_ready_after_the_old_one_minute_timeout(self):
  code,calls,state,output=self.scenario('cold-delayed');self.assertEqual(code,0,output)
  self.assertEqual(state['public_url'],'https://fresh-current.trycloudflare.com')
  self.assertEqual(sum(c['kind']=='start-tunnel' for c in calls),1)
  public=[c for c in calls if c['kind']=='probe' and c['value'].startswith('https:')]
  self.assertGreaterEqual(public[0]['seconds'],5)
  self.assertGreaterEqual(public[-1]['seconds'],90)
  self.assertEqual(self.probes[0]['category'],'dns');self.assertEqual(self.probes[-1]['category'],'ok')
 def test_retrying_start_preserves_a_healthy_origin_during_public_failure(self):
  code,calls,state,output=self.scenario('recover-no-reload');self.assertEqual(code,0,output)
  self.assertFalse(any(c['kind']=='start-server' for c in calls))
  self.assertEqual([c['value'] for c in calls if c['kind']=='stop'],[1002])
  self.assertEqual(state['server_pid'],1001)
  self.assertEqual(state['public_url'],'https://fresh-current.trycloudflare.com')
 def test_failed_new_tunnel_is_replaced_once_without_restarting_origin(self):
  code,calls,state,output=self.scenario('cold-rebuild');self.assertEqual(code,0,output)
  self.assertEqual(state['public_url'],'https://replacement-current.trycloudflare.com')
  starts=[c for c in calls if c['kind']=='start-tunnel']
  self.assertEqual(len(starts),2);self.assertGreaterEqual(starts[1]['seconds'],180)
  self.assertNotEqual(starts[0]['value'],starts[1]['value'])
  self.assertEqual(sum(c['kind']=='start-server' for c in calls),1)
 def test_persistent_failure_is_bounded_and_does_not_publish_an_unverified_url(self):
  for scenario,category in [('cold-timeout','timeout'),('cold-tls','tls'),('cold-html','invalid_response'),('cold-http','http_502')]:
   with self.subTest(scenario=scenario):
    code,calls,state,output=self.scenario(scenario);self.assertEqual(code,1,output)
    self.assertNotIn('public_url',state)
    self.assertEqual(sum(c['kind']=='start-tunnel' for c in calls),2)
    self.assertEqual(sum(c['kind']=='start-server' for c in calls),1)
    self.assertEqual({p['category'] for p in self.probes},{category})
    self.assertLess(max(c['seconds'] for c in calls),370)
 def test_origin_failure_is_not_misdiagnosed_as_a_tunnel_failure(self):
  code,calls,state,output=self.scenario('cold-origin-fails');self.assertEqual(code,1,output)
  self.assertEqual(sum(c['kind']=='start-tunnel' for c in calls),1)
  self.assertNotIn('public_url',state)
 def test_unregistered_tunnel_is_bounded_and_never_probed_or_published(self):
  code,calls,state,output=self.scenario('cold-unregistered');self.assertEqual(code,1,output)
  self.assertEqual(sum(c['kind']=='start-tunnel' for c in calls),2)
  self.assertNotIn('public_url',state);self.assertFalse(self.probes)
 @unittest.skipUnless(shutil.which('pwsh.exe'),'PowerShell 7 is not installed')
 def test_powershell7_preserves_the_saved_utc_process_identity(self):
  for scenario in ('healthy','recover','stop'):
   with self.subTest(scenario=scenario):
    code,calls,state,output=self.scenario(scenario,'pwsh.exe');self.assertEqual(code,0,output)
    if scenario=='healthy':
     self.assertFalse(any(c['kind'].startswith('start') or c['kind']=='stop' for c in calls))
    else:self.assertEqual(sorted(c['value'] for c in calls if c['kind']=='stop'),[1001,1002])

if __name__=='__main__':unittest.main(verbosity=2)
