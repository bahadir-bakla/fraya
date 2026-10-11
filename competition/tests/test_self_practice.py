import copy,json,pathlib,sys,tempfile,types,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import builder,self_practice
KIT=builder.KIT
PUBLIC=json.load(open(KIT/'public-test-set.json'));API=json.load(open(KIT/'tools/openapi.json'))
FACTS=self_practice.public_facts(KIT)
class ValidateCasesTests(unittest.TestCase):
    def test_public_cases_are_valid_and_relabelled(self):
        kept,problems=self_practice.validate_cases(copy.deepcopy(PUBLIC),FACTS,API)
        self.assertEqual((len(kept),problems),(13,[]))
        self.assertTrue(all(c['brief']==self_practice.GROUP for c in kept))
        self.assertEqual(next(c for c in kept if c['id']=='PUB-10')['faults'],next(c for c in PUBLIC if c['id']=='PUB-10')['faults'])
    def test_changed_facts_duplicates_and_bad_enums_are_dropped(self):
        a,b,c,d=(copy.deepcopy(PUBLIC[i]) for i in (0,0,1,2))
        a['identity']={'date_of_birth':'1900-01-01','phone_last4':'0000'}
        c['expected']['transfers']=[{'queue':'billing'}]
        d['expected']['promises']=[{'product_id':'p9','amount':10,'date':'2026-10-15'}]
        kept,problems=self_practice.validate_cases([a,copy.deepcopy(PUBLIC[3]),copy.deepcopy(PUBLIC[3]),c,d],FACTS,API)
        self.assertEqual([k['id'] for k in kept],['PUB-04'])
        self.assertEqual(len(problems),4)
    def test_non_list_input_keeps_nothing(self):
        self.assertEqual(self_practice.validate_cases({'not':'a list'},FACTS,API),([],[]))
class AgreeTests(unittest.TestCase):
    def test_only_identical_unambiguous_ledgers_are_kept(self):
        one,two,three=(dict(copy.deepcopy(PUBLIC[i]),case_label=f'T-0{i}') for i in (0,1,2))
        audit=[{'file':'train.json','case_label':'T-00','verdict':'ok','expected':copy.deepcopy(one['expected'])},
               {'file':'train.json','case_label':'T-01','verdict':'ambiguous','expected':copy.deepcopy(two['expected'])},
               {'file':'train.json','case_label':'T-02','verdict':'ok','expected':dict(copy.deepcopy(three['expected']),outcome='paid')}]
        audit[0]['expected']['promises'][0]['amount']=420  # integer vs float must still match
        kept,dropped=self_practice.agree({'train.json':[one,two,three]},audit)
        self.assertEqual([c['case_label'] for _,c in kept],['T-00'])
        self.assertEqual(sorted(d['case'] for d in dropped),['T-01','T-02'])
class ArgumentTests(unittest.TestCase):
    def parse(self,*extra):
        with patch.object(sys,'argv',['builder.py','/tmp/unseen-brief.md','--model','test',*extra]):return builder.arguments()
    def test_self_practice_defaults_to_four_rounds_and_allows_unseen_briefs(self):
        self.assertEqual(self.parse('--self-practice').rounds,4)
    def test_self_practice_cannot_skip_tests(self):
        with self.assertRaises(SystemExit):self.parse('--self-practice','--skip-tests')
class FinishTests(unittest.TestCase):
    def fake(self,directory):
        work=pathlib.Path(directory);published=[];events=[];tests=[]
        run=types.SimpleNamespace(work=work,status={'freya':{'agent_id':'a','workflow_id':'w','version':3}},remaining=lambda:900,
            publish=lambda wf:published.append(wf),event=lambda kind,**d:events.append(kind),
            test=lambda ids,n,**kw:tests.append(kw) or {'passed':4,'total':5,'official_passed':2})
        return run,published,events,tests
    def candidate(self,root,number,passed):
        folder=pathlib.Path(root)/f'round-{number}';folder.mkdir()
        for name in ('workflow.json','policy.json','coverage.json'):(folder/name).write_text(json.dumps({'round':number}))
        return {'round':number,'passed':passed,'total':8,'folder':folder,'version':number}
    def test_better_earlier_candidate_is_restored_then_holdout_measured(self):
        with tempfile.TemporaryDirectory() as directory:
            run,published,events,tests=self.fake(directory)
            candidates=[self.candidate(directory,1,7),self.candidate(directory,2,5)]
            done=builder.Run.finish_self_practice(run,candidates,{'holdout':'h.json'})
            self.assertTrue(done);self.assertEqual(published,[{'round':1}]);self.assertIn('self_practice_restored',events)
            self.assertEqual(run.status['holdout'],{'passed':4,'total':5,'official_passed':2})
            self.assertEqual(tests[0]['label'],'holdout');self.assertFalse(tests[0]['repair_feedback'])
    def test_latest_candidate_kept_on_ties(self):
        with tempfile.TemporaryDirectory() as directory:
            run,published,events,tests=self.fake(directory)
            builder.Run.finish_self_practice(run,[self.candidate(directory,1,6),self.candidate(directory,2,6)],{})
            self.assertEqual(published,[]);self.assertEqual(run.status['self_practice_choice']['round'],2);self.assertEqual(tests,[])
class AdjustReasonTests(unittest.TestCase):
    def test_reason_only_rejection_is_counted_with_the_agents_values(self):
        import simulate,score
        case=dict(copy.deepcopy(PUBLIC[2]),expected={'outcome':'not_verified','reason':'NVF-FAIL','promises':[],'notes':[],'callbacks':[],'transfers':[]})
        ledger={'outcome':None,'reason':None,'promises':[],'notes':[],'callbacks':[],'transfers':[],
                'calls':[{'tool':'close_call','args':{'outcome':'not_verified','reason':'NVF-FAIL'},'result':{'ok':False,'error':'this outcome needs one of these reasons: failed, declined'}}]}
        with tempfile.TemporaryDirectory() as directory:
            cases=pathlib.Path(directory)/'cases.json';cases.write_text(json.dumps([case]))
            report=pathlib.Path(directory)/'r.json';report.write_text(json.dumps({'passed':0,'total':1,'rows':[{'id':case['id'],'pass':False,'failed':['outcome (None, None)'],'customer_id':'c1'}]}))
            with patch.object(score,'http',lambda path,body=None:ledger):simulate.adjust_reason_rejections(report,cases)
            result=json.loads(report.read_text())
        self.assertEqual((result['passed'],result['official_passed']),(1,0));self.assertTrue(result['rows'][0]['reason_adjusted'])
if __name__=='__main__':unittest.main()
