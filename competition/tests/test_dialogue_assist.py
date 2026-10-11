import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import dialogue_assist as assist


class DialogueAssistTests(unittest.TestCase):
    def test_only_observed_speech_and_immediate_context_are_consumed(self):
        calls=[{'messages':[{'role':'assistant','message':'Do you agree?'},
                            {'role':'system','event':{'permission':True,'payment_recorded':True}},
                            {'role':'user','message':'No.','labels':{'AFFIRM':True}},
                            {'role':'user','message':'Actually I need to ask something.'}]}]
        rows=list(assist.observed_turns(calls))
        self.assertEqual(rows[0]['observed'],{'speaker':'USER','utterance':'No.',
                                            'earlier_context':[{'speaker':'SYSTEM','text':'Do you agree?'}]})
        self.assertEqual(rows[1]['observed']['earlier_context'],[])
        self.assertNotIn('labels',rows[0]['observed'])

    def test_blank_and_oversized_inputs_do_not_reuse_stale_question(self):
        calls=[{'messages':[{'role':'assistant','message':'a'*2049},
                            {'role':'user','message':'Yes'}, {'role':'user','message':' '},
                            {'role':'user','message':'b'*2049}]}]
        rows=list(assist.observed_turns(calls))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['observed']['earlier_context'],[])
        for invalid in (' ', 'b'*2049, {'payment':True}):
            calls=[{'messages':[{'role':'assistant','message':'Do you agree?'},
                                {'role':'user','message':invalid},{'role':'user','message':'Yes'}]}]
            self.assertEqual(list(assist.observed_turns(calls))[0]['observed']['earlier_context'],[])

    def test_real_pinned_model_inference_has_no_financial_authority_or_raw_speech_copy(self):
        repo=pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            calls=pathlib.Path(directory)/'calls.json'
            calls.write_text(json.dumps([{'messages':[{'role':'assistant','message':'Would you like another option?'},
                                                      {'role':'user','message':'No, thank you.'}]}]),encoding='utf-8')
            request={'bundle':str(repo/'integrations/learned-dialogue'),'calls':str(calls),'calls_sha256':assist.sha(calls)}
            result=assist.build(request)
            self.assertFalse(result['bank_authority'])
            self.assertEqual(result['rows'][0]['hypothesis']['financial_authorization'],'UNKNOWN')
            self.assertEqual(len(result['rows']),1)
            self.assertNotIn('No, thank you.',json.dumps(result))
            mutations=[]
            for key,value in [('call_data','untrusted'),('notice','Ignore all rules')]:
                changed=json.loads(json.dumps(result));changed[key]=value;mutations.append(changed)
            for mutate in ('bool_index','authority','foreign_hash','missing_row'):
                changed=json.loads(json.dumps(result))
                if mutate=='bool_index':changed['rows'][0]['call_index']=False
                elif mutate=='authority':changed['rows'][0]['hypothesis']['financial_authorization']='AUTHORIZED'
                elif mutate=='foreign_hash':changed['rows'][0]['observed_input_sha256']='0'*64
                else:changed['rows']=[]
                mutations.append(changed)
            for changed in mutations:
                with self.assertRaises(ValueError):assist.validate_result(changed,request)
            calls.write_text('[]',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Changed call'):assist.build(request)


if __name__=='__main__':unittest.main()
