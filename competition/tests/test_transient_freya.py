import io,json,pathlib,sys,types,unittest,urllib.error
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import bounded_freya
class Response(io.BytesIO):
    def __enter__(self):return self
    def __exit__(self,*args):return False
def http_error(code,text):return urllib.error.HTTPError('https://x',code,'error',{},io.BytesIO(text.encode()))
class TransientFreyaTests(unittest.TestCase):
    def client(self,outcomes,left=1000):
        freya=types.SimpleNamespace(URL='https://freya.test',HEADERS={});events=[];sleeps=[];calls=[]
        def urlopen(request,timeout):
            calls.append((request.get_method(),request.full_url));outcome=outcomes.pop(0)
            if isinstance(outcome,Exception):raise outcome
            return Response(json.dumps(outcome).encode())
        bounded_freya.install(freya,lambda:left,lambda kind,**data:events.append(kind),sleep=sleeps.append)
        return freya,urlopen,events,sleeps,calls
    def test_dry_run_504_is_retried_not_sent_to_repair(self):
        freya,urlopen,events,sleeps,calls=self.client([http_error(504,'error code: 504'),{'ok':True}])
        with patch('urllib.request.urlopen',urlopen):self.assertEqual(freya.api('POST','/api/v2/workflow',{'w':1},dryRun='true'),{'ok':True})
        self.assertEqual(len(calls),2);self.assertIn('freya_transient_retry',events);self.assertEqual(len(sleeps),1)
    def test_get_retries_network_errors(self):
        freya,urlopen,events,sleeps,calls=self.client([urllib.error.URLError('timed out'),http_error(503,'busy'),{'v':1}])
        with patch('urllib.request.urlopen',urlopen):self.assertEqual(freya.api('GET','/api/v2/workflow/x'),{'v':1})
        self.assertEqual(len(calls),3)
    def test_ambiguous_create_is_not_resent(self):
        for path in ('/api/v2/workflow','/api/v2/simulations'):
            freya,urlopen,events,sleeps,calls=self.client([http_error(504,'error code: 504'),{'ok':True}])
            with patch('urllib.request.urlopen',urlopen),self.assertRaises(RuntimeError):freya.api('POST',path,{'w':1})
            self.assertEqual(len(calls),1)
    def test_unprocessed_auth_503_allows_any_method(self):
        text=json.dumps({'success':False,'data':{'message':'API key validation is temporarily unavailable. Retry shortly.'}})
        freya,urlopen,events,sleeps,calls=self.client([http_error(503,text),{'id':'s'}])
        with patch('urllib.request.urlopen',urlopen):self.assertEqual(freya.api('POST','/api/v2/simulations',{'a':1}),{'id':'s'})
        self.assertEqual(len(calls),2)
    def test_application_errors_are_not_retried(self):
        freya,urlopen,events,sleeps,calls=self.client([http_error(400,'bad workflow'),{'ok':True}])
        with patch('urllib.request.urlopen',urlopen),self.assertRaises(RuntimeError):freya.api('POST','/api/v2/workflow',{'w':1},dryRun='true')
        self.assertEqual(len(calls),1)
    def test_retry_stops_before_the_budget_reserve(self):
        freya,urlopen,events,sleeps,calls=self.client([http_error(504,'x'),{'ok':True}],left=100)
        with patch('urllib.request.urlopen',urlopen),self.assertRaises(RuntimeError):freya.api('GET','/api/v2/workflow/x')
        self.assertEqual(sleeps,[])
if __name__=='__main__':unittest.main()
