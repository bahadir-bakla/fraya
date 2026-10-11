"""V2 keeps self-answer context without crossing tool/call boundaries."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finetuned_assist import observed_turns


class V2ContextTests(unittest.TestCase):
    def test_self_answer_and_question_retained_only_v2(self):
        calls=[{'messages':[{'role':'user','message':'I agree to Monday.'},{'role':'assistant','message':'Still Monday?'},{'role':'user','message':'I withdraw that yes.'}]}]
        rows,_=observed_turns(calls,context_turns=2)
        self.assertEqual(rows[-1]['input']['previous_utterances'],[{'speaker':'USER','text':'I agree to Monday.'},{'speaker':'ASSISTANT','text':'Still Monday?'}])
        legacy,_=observed_turns(calls)
        self.assertEqual(legacy[-1]['input']['previous_utterances'],[{'speaker':'ASSISTANT','text':'Still Monday?'}])

    def test_tool_and_call_boundaries_reset_two_turn_context(self):
        calls=[{'messages':[{'role':'user','message':'Earlier yes.'},{'role':'tool','message':'receipt'},{'role':'assistant','message':'New question?'},{'role':'user','message':'No.'}]},{'messages':[{'role':'user','message':'New call.'}]}]
        rows,_=observed_turns(calls,context_turns=2)
        self.assertEqual(rows[1]['input']['previous_utterances'],[{'speaker':'ASSISTANT','text':'New question?'}])
        self.assertEqual(rows[2]['input']['previous_utterances'],[])

    def test_invalid_turn_cannot_retain_old_self_answer(self):
        for invalid in (None,{'role':'assistant','message':''},{'role':'system','message':'phase=confirm'}):
            calls=[{'messages':[{'role':'user','message':'Old yes.'},invalid,{'role':'user','message':'Current answer.'}]}]
            rows,_=observed_turns(calls,context_turns=2)
            self.assertEqual(rows[-1]['input']['previous_utterances'],[])

    def test_only_last_two_utterances_and_no_oracle_fields(self):
        calls=[{'bank_state':'not-feature','messages':[{'role':'user','message':'Old name.'},{'role':'assistant','message':'Question.'},{'role':'user','message':'My last answer.'},{'role':'assistant','message':'Confirm?','phase':'not-feature'},{'role':'user','message':'No, corrected.','labels':[1]*7}]}]
        rows,_=observed_turns(calls,context_turns=2)
        self.assertEqual(rows[-1]['input']['previous_utterances'],[{'speaker':'USER','text':'My last answer.'},{'speaker':'ASSISTANT','text':'Confirm?'}])
        self.assertEqual(set(rows[-1]['input']),{'current_utterance','previous_utterances'})


if __name__=='__main__':unittest.main()
