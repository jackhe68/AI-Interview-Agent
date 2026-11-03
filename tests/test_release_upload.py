"""Real PS5/PS7 control flow; all packaging inputs fictional, remote calls replaced."""
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from test_release_package import ROOT,release

class UploadTests(unittest.TestCase):
    def scenario(self,shell,name):
        with tempfile.TemporaryDirectory(prefix='code-upload-') as temp:
            root=Path(temp)
            for entry in release.RELEASE_FILES:
                path=root/entry;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fictional code')
            for entry in ('deploy/package_release.py','deploy/upload.ps1'):
                shutil.copy2(ROOT/entry,root/entry)
            run=subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tests/upload_fixture.ps1'),
                                '-Project',str(root),'-TestPython',sys.executable,'-Scenario',name],capture_output=True,timeout=30)
            calls=json.loads((root/'calls.json').read_text(encoding='utf-8-sig')) if (root/'calls.json').exists() else []
            return run.returncode,calls,run.stdout.decode(errors='replace')

    def test_success_and_local_review(self):
        for shell in ('powershell.exe','pwsh.exe'):
            if not shutil.which(shell):continue
            for name,expected in [('success',['package','verify','scp','ssh']),('local-only',['package','verify'])]:
                with self.subTest(shell=shell,name=name):
                    code,calls,output=self.scenario(shell,name);self.assertEqual(code,0,output);self.assertEqual(calls,expected)

    def test_failure_stops_the_following_operations(self):
        cases=[('package-fail',['package']),('no-archive',['package']),('verify-fail',['package','verify']),
               ('scp-fail',['package','verify','scp']),('ssh-fail',['package','verify','scp','ssh']),('invalid-target',[])]
        for shell in ('powershell.exe','pwsh.exe'):
            if not shutil.which(shell):continue
            for name,expected in cases:
                with self.subTest(shell=shell,name=name):
                    code,calls,output=self.scenario(shell,name);self.assertNotEqual(code,0,output);self.assertEqual(calls,expected)

if __name__=='__main__':unittest.main(verbosity=2)
