import datetime,json,pathlib,sys,tempfile,time,types,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import builder,bounded_freya
class BudgetTests(unittest.TestCase):
    def test_partial_process_output_cannot_block_the_deadline(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(builder,'ROOT',pathlib.Path(directory)):
            args=types.SimpleNamespace(brief=None,briefs=[str(builder.KIT/'briefs/brief-a.md')],minutes=1,resume_run=None,slot='partial',model='test')
            run=builder.Run(args);started=time.monotonic()
            with self.assertRaises(TimeoutError):run.child([sys.executable,'-c','import sys,time;sys.stdout.write("partial");sys.stdout.flush();time.sleep(5)'],timeout=0.2,purpose='partial-output deadline probe')
            self.assertLess(time.monotonic()-started,2)
    def test_wall_clock_jump_exhausts_budget_even_if_monotonic_clock_does_not_advance(self):
        run=object.__new__(builder.Run);run.deadline=1000;run.wall_deadline=2000
        with patch('builder.time.monotonic',return_value=500),patch('builder.time.time',return_value=2001):self.assertEqual(run.remaining(),0)
    def test_exhausted_budget_makes_no_http_request(self):
        client=types.SimpleNamespace(URL='https://example.invalid',HEADERS={})
        bounded_freya.install(client,lambda:0)
        with patch('bounded_freya.urllib.request.urlopen') as request:
            with self.assertRaises(TimeoutError):client.api('POST','/api/v2/workflow',{})
            request.assert_not_called()
    def test_http_timeout_cannot_exceed_remaining_budget(self):
        client=types.SimpleNamespace(URL='https://example.invalid',HEADERS={});bounded_freya.install(client,lambda:4)
        response=unittest.mock.MagicMock();response.__enter__.return_value.read.return_value=b'{"success":true,"data":{"result":{"valid":true}}}'
        with patch('bounded_freya.urllib.request.urlopen',return_value=response) as request:
            self.assertEqual(client.api('GET','/api/v2/workspaces'),{'valid':True})
            self.assertEqual(request.call_args.kwargs['timeout'],4)
    def test_resume_preserves_elapsed_time_and_never_extends_original_limit(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(builder,'ROOT',pathlib.Path(directory)):
            run=pathlib.Path(directory)/'runs/stopped';(run/'work').mkdir(parents=True)
            started=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(seconds=120)).isoformat()
            (run/'status.json').write_text(json.dumps({'phase':'failed','started':started,'slot':'same','model':'same-model','round':1,'maximum_minutes':10}))
            args=types.SimpleNamespace(brief=None,briefs=[str(builder.KIT/'briefs/brief-a.md')],minutes=30,resume_run='stopped',slot='same',model='same-model')
            resumed=builder.Run(args)
            self.assertEqual(args.minutes,10);self.assertGreater(resumed.remaining(),470);self.assertLess(resumed.remaining(),481)
if __name__=='__main__':unittest.main()
