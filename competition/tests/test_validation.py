import copy,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from validation import validate,validate_coverage
API=json.loads((ROOT.parent/'build-the-builder 2/tools/openapi.json').read_text())
BASE=json.loads((ROOT.parent/'build-the-builder 2/examples/base-agent.json').read_text())
def without_null(value):
    if isinstance(value,dict):return {k:without_null(v) for k,v in value.items() if v is not None}
    if isinstance(value,list):return [without_null(v) for v in value if v is not None]
    return value
def specimen():
    # Match the current supplied schema instead of copying the example's incomplete close table.
    workflow=without_null(copy.deepcopy(BASE))
    for node in workflow['nodes'].values():
        for tool in node['tools']:
            if tool['function']['handler']=='__function__:api_call':
                name=tool['function']['name'];schema=copy.deepcopy(API['paths']['/'+name]['post']['requestBody']['content']['application/json']['schema'])
                tool['function']['parameters']['properties']['body']=schema
    for tool in workflow['tools']:
        name=tool['function']['name'];schema=copy.deepcopy(API['paths']['/'+name]['post']['requestBody']['content']['application/json']['schema']);tool['function']['parameters']['properties']['body']=schema
    return workflow
class StructuralValidationTests(unittest.TestCase):
    def test_wrong_allowlisted_endpoint_and_method_are_rejected(self):
        workflow=specimen();tool=workflow['nodes']['identity']['tools'][0]
        props=tool['function']['parameters']['properties']
        props['url']['default']=API['servers'][0]['url'].rstrip('/')+'/create_promise'
        self.assertTrue(any('bound endpoint' in e for e in validate(workflow,API)))
        workflow=specimen();tool=workflow['nodes']['identity']['tools'][0]
        tool['function']['parameters']['properties']['method']['default']='DELETE'
        self.assertTrue(any('method/URL' in e for e in validate(workflow,API)))
    def test_empty_unknown_and_omitted_coverage_are_rejected(self):
        for coverage in ({},{'rules':[]},{'rules':[{'rule':'Guard','status':'unknown'}]},{'rules':[{'rule':'Guard','status':'omitted'}]}):
            self.assertTrue(validate_coverage(coverage))
    def test_disclosed_loss_of_mandatory_guards_blocks_publication(self):
        self.assertTrue(validate_coverage({'rules':[{'rule':'Payment guard','status':'implemented with explicitly degraded enforcement'}]}))
        self.assertFalse(validate_coverage({'rules':[{'rule':'Payment guard','status':'implemented'}],'limitations':['Natural-language extraction is model-dependent.']}))
    def test_current_api_matching_schema_passes(self):self.assertEqual(validate(specimen(),API),[])
    def test_empty_speech_on_an_action_node_is_rejected(self):
        workflow=specimen();workflow['nodes']['identity']['on_enter']={'type':'tts','text':''}
        self.assertTrue(any('empty TTS' in e for e in validate(workflow,API)))
    def test_new_tool_schema_changes_are_detected(self):
        workflow=specimen();tool=workflow['nodes']['identity']['tools'][0]
        tool['function']['parameters']['properties']['body']['properties']['answer']['type']='integer'
        self.assertTrue(any('incorrect type' in e for e in validate(workflow,API)))
    def test_unapproved_endpoints_are_rejected(self):
        workflow=specimen();workflow['nodes']['identity']['tools'][0]['function']['parameters']['properties']['url']['default']='https://example.com/exfiltrate'
        self.assertTrue(any('outside supplied' in e for e in validate(workflow,API)))
    def test_python_syntax_and_forbidden_io_fail(self):
        workflow=specimen();workflow['nodes']['identity']['tools'][0]['pre_process_code']="open('/tmp/customer').read()"
        self.assertTrue(any('forbidden call' in e for e in validate(workflow,API)))
        workflow['nodes']['identity']['tools'][0]['pre_process_code']='if:'
        self.assertTrue(any('Python syntax' in e for e in validate(workflow,API)))
    def test_control_state_does_not_depend_on_global_scope(self):
        workflow=specimen();workflow['nodes']['identity']['tools'][0]['pre_process_code']='def advance():\n    global line\n    line = "Confirm your payment"\n'
        self.assertTrue(any('global control writes' in e for e in validate(workflow,API)))
    def test_double_braces_null_and_missing_routes_fail(self):
        workflow=specimen();workflow['system_prompt']=None;workflow['nodes']['identity']['transitions'][0]['target_node']='missing'
        workflow['nodes']['identity']['tools'][0]['pre_process_code']='x = {{bad}}'
        errors=validate(workflow,API)
        self.assertTrue(any('null' in e for e in errors));self.assertTrue(any('missing transition' in e for e in errors));self.assertTrue(any('double-curly' in e for e in errors))
    def test_retries_on_writes_and_bad_response_mappings_fail(self):
        workflow=specimen();tool=workflow['nodes']['collection']['tools'][1];tool['config']['maxRetries']=2;tool['response_mapping']=[{'path':'ok','variable':'ok'}]
        errors=validate(workflow,API);self.assertTrue(any('write retries' in e for e in errors));self.assertTrue(any('data.' in e for e in errors))
    def test_phone_agent_model_is_not_builder_config(self):
        workflow=specimen();workflow['agent_config']={'llmConfig':{'model':'invented'}}
        self.assertTrue(any('agent_config' in e for e in validate(workflow,API)))
if __name__=='__main__':unittest.main()
