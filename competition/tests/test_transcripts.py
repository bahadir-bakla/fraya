import json,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from transcripts import compact_messages
class TranscriptTests(unittest.TestCase):
    def test_bank_state_changes_and_failed_tools_are_preserved(self):
        messages=[{'role':'system','message':json.dumps({'event':'route_evaluated','from_node':'security','target':'collection','variable_table':{'verified':'yes','system.iso_utc_now':'unrelated'}})}, {'role':'system','message':json.dumps({'event':'function_call_complete','function':'api_call','result':{'data':{'ok':False,'error':'temporarily unavailable'}}})}]
        output=compact_messages(messages)
        self.assertEqual(output[0]['event']['variable_updates'],{'verified':'yes'})
        self.assertFalse(output[1]['event']['result']['data']['ok'])
    def test_dialogue_and_code_identity_survive_without_repeated_snapshots(self):
        output=compact_messages([{'role':'assistant','message':'Please confirm.','workflowSnapshot':{'huge':'snapshot'}},{'role':'system','message':json.dumps({'event':'function_call_start','function':'code_exec','args':{'code':'pass'}})}])
        self.assertEqual(output[0]['message'],'Please confirm.');self.assertNotIn('workflowSnapshot',output[0])
        self.assertEqual(len(output[1]['event']['code_sha256']),64)
if __name__=='__main__':unittest.main()
