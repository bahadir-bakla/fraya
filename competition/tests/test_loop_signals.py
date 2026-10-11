import json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from transcripts import loop_signals
def say(role,text):return {'role':role,'message':text}
def sys_event(event):return {'role':'system','message':json.dumps(event)}
class LoopSignalTests(unittest.TestCase):
    def test_repeated_agent_question_is_a_loop(self):
        ask='The payment date must be today or later. Which exact day do you mean?'
        messages=[say('assistant',ask),say('user','today'),say('assistant',ask),say('user','I mean today'),say('assistant',ask)]
        kinds=[s['kind'] for s in loop_signals(messages)]
        self.assertIn('agent_repeats_line',kinds)
    def test_caller_repeating_the_same_answer_is_a_loop(self):
        messages=[say('assistant','a?'),say('user','Monday the twenty sixth.'),say('assistant','b?'),say('user','Monday the twenty sixth.'),say('assistant','c?'),say('user','Monday the twenty sixth.')]
        self.assertIn('caller_repeats_answer',[s['kind'] for s in loop_signals(messages)])
    def test_timeout_and_verified_not_verified_close(self):
        messages=[sys_event({'event':'function_call_complete','function':'api_call','result':{'data':{'ok':True,'all_verified':True}}}),
                  sys_event({'event':'function_call_start','function':'api_call','args':{'url':'https://bank/v1/close_call','body':{'outcome':'not_verified','reason':'declined'}}})]
        kinds=[s['kind'] for s in loop_signals(messages,'exceeded-max-duration')]
        self.assertEqual(sorted(kinds),['call_timed_out','verified_call_closed_not_verified'])
    def test_normal_call_has_no_signals(self):
        messages=[say('assistant','May I speak with Daniel Reyes?'),say('user','Yes, this is Daniel.'),say('assistant','What is your date of birth?'),say('user','14 March 1988.'),say('assistant','Thank you. Goodbye.')]
        self.assertEqual(loop_signals(messages,'assistant-ended-call'),[])
    def test_short_repeated_acknowledgements_are_not_loops(self):
        messages=[say('assistant','Thank you.')]*4
        self.assertEqual(loop_signals(messages),[])
if __name__=='__main__':unittest.main()
