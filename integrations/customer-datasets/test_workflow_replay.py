"""Checks of honest subset execution, not tests that copy bank policies."""
from copy import deepcopy
import unittest
import workflow_replay as r


class WorkflowReplayTests(unittest.TestCase):
    def test_authored_program_never_reads_expected_or_reference_actions(self):
        case=r.b.fresh_case('full_payment',0)
        original=r.program(case)
        case['expected']={'unavailable':True};case['execution']['reference_tool_calls']=None
        self.assertEqual(r.program(case),original)
        self.assertNotIn('expected',str(original))

    def test_third_party_program_has_no_security_answers(self):
        case=r.b.fresh_case('callback_boundary',0)
        events=r.program(case)
        self.assertNotIn('security_answer',[x['kind'] for x in events])
        for x in events:self.assertEqual(x['answer'],'')

    def test_positive_identity_is_authored_from_actual_leap_day_fixture(self):
        case=r.b.fresh_case('full_payment',0)
        case['facts']['identity']['date_of_birth']='1988-02-29'
        answers=[e['answer'] for e in r.program(case) if e['kind']=='security_answer']
        self.assertEqual(answers[0],'29 February 1988')

    def test_aggregate_total_is_an_actor_fact_not_expected_oracle(self):
        case=r.b.fresh_case('split_deadlines',0)
        case['expected']={};case['execution']['reference_tool_calls']=None
        proposal=next(e for e in r.program(case,aggregate_total=True) if e['kind']=='proposal')
        self.assertEqual(proposal['amount'],sum(p['past_due'] for p in case['facts']['products']))
        self.assertEqual(proposal['product'],'all')
        self.assertIn('in total',proposal['raw'])

    def test_unbound_http_operation_cannot_be_dispatched_to_local_bank(self):
        case=r.b.fresh_case('full_payment',0)
        for method,path,error in [('DELETE','/verify_identity','unsupported_or_unbound_http_operation'),
                                  ('POST','/get_account','function_endpoint_binding_mismatch')]:
            parameters={'type':'object','properties':{
                'url':{'type':'string','default':r.b.local.API['servers'][0]['url'].rstrip('/')+path},
                'method':{'type':'string','default':method},
                'body':{'type':'object','properties':{},'default':{}}}}
            workflow={'initial_node':'action','nodes':{'action':{
                'node_type':'code','on_enter':{'type':'silent'},'pre_actions':[{'function':{'name':'verify_identity','handler':'__function__:api_call','parameters':parameters}}],
                'transitions':[{'condition':{'operator':'always'},'target_node':'end'}]},'end':{'node_type':'end_call'}}}
            replay=r.Replay(workflow,case)
            result=replay.run([])
            self.assertEqual(result['error'],error)
            self.assertEqual(result['ledger']['calls'],[])
            self.assertFalse(result['kernel_ledger_pass'])

    def test_template_resolution_preserves_zero_phone_and_numeric_types(self):
        values={'suffix':'0007','money':66}
        self.assertEqual(r.defaults({'type':'string','default':'{{suffix}}'},values),'0007')
        self.assertEqual(r.defaults({'type':'number','default':'{{money}}'},values),66.0)
        with self.assertRaises(r.ReplayError):r.render('{{missing}}',values)

    def test_unknown_semantic_routes_and_model_filled_actions_fail(self):
        with self.assertRaises(r.ReplayError):r.condition({'mode':'ai','operator':'equals'}, {})
        with self.assertRaises(r.ReplayError):r.defaults({'type':'object','required':['answer'],'properties':{'answer':{'type':'string'}}},{})

    def test_unknown_extraction_fields_fail_instead_of_inventing_values(self):
        with self.assertRaises(r.ReplayError):r.assign_event([{'name':'unknown','type':'string'}],r.event('yes','yes'),{})
        values={};r.assign_event([{'name':'event','type':'string'}],r.event('yes','yes'),values)
        self.assertIn('event',values)

    def test_exported_code_cannot_use_io_or_arbitrary_imports(self):
        for code in ('import os','open("data")','x=vars.__class__'):
            with self.assertRaises(r.ReplayError):r.Code().run(code,{})

    def test_default_and_split_namespace_probes_are_explicit(self):
        values={};r.Code().run('import json\ndef advance(v):\n v["ok"]=json.dumps(True)\nadvance(vars)',values)
        self.assertEqual(values['ok'],'true')
        with self.assertRaises(NameError):r.Code(split_scopes=True).run('import json\ndef advance(v):\n v["ok"]=json.dumps(True)\nadvance(vars)',{})

    def test_reference_expected_cannot_make_ended_without_close_pass(self):
        case=r.b.fresh_case('full_payment',0)
        workflow={'initial_node':'end','nodes':{'end':{'node_type':'end_call'}}}
        result=r.Replay(workflow,case).run([])
        self.assertEqual(result['error'],'ended_without_bank_close')
        self.assertFalse(result['kernel_ledger_pass'])
        self.assertIsNone(result['voice_agent_pass'])

    def test_loop_stops_with_an_explicit_budget_failure(self):
        case=r.b.fresh_case('full_payment',0)
        workflow={'initial_node':'loop','nodes':{'loop':{'node_type':'code','on_enter':{'type':'silent'},'transitions':[{'condition':{'operator':'always'},'target_node':'loop'}]}}}
        result=r.Replay(workflow,case,max_steps=3).run([])
        self.assertEqual(result['error'],'node_step_budget_exhausted')
        self.assertEqual(len(result['node_visits']),3)
        self.assertFalse(result['kernel_ledger_pass'])


if __name__=='__main__':unittest.main()
