"""Source acquisition integrity tests; no detector, policy, labels or score changes."""
import hashlib
import json
import re
import unittest
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'research/customer-benchmark/semantic-v6-peer-extension'

def read(name):
    return json.loads((DATA / name).read_text(encoding='utf-8'))

def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def sha(x):
    return hashlib.sha256(x).hexdigest()

def pointer(document, path):
    value=document
    for part in path.lstrip('/').split('/'):
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value

def keys(value):
    if isinstance(value,dict):
        for k,v in value.items():
            yield k
            yield from keys(v)
    elif isinstance(value,list):
        for v in value:
            yield from keys(v)

class PeerAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta=read('author-metadata.parent-only.json')
        cls.packet=read(cls.meta['source_packet'])
        cls.blind=read(cls.meta['blind_packet'])
        cls.closure=read('review-closure.json')
        cls.audit=read('lineage-audit.parent-only.json')
        cls.manifest=read('build-manifest.json')
        cls.contract=json.loads((ROOT / cls.meta['contract_file']).read_text(encoding='utf-8'))

    def assert_span(self, span, document):
        text=pointer(document,span['raw_field_path'])
        a,b=span['char_start'],span['char_end']
        self.assertTrue(0 <= a < b <= len(text))
        self.assertEqual(span['offset_unit'],'python_unicode_codepoints')
        self.assertEqual(text[a:b],span['text'])
        self.assertEqual(len(text[:a].encode('utf-8')),span['utf8_byte_start'])
        self.assertEqual(len(text[:b].encode('utf-8')),span['utf8_byte_end'])
        self.assertEqual(text.encode('utf-8')[span['utf8_byte_start']:span['utf8_byte_end']].decode('utf-8'),span['text'])

    def test_exact_v5_and_blind_schemas(self):
        self.assertEqual(read('collection.schema.json'),self.contract['collection_json_schema'])
        self.assertEqual(read('independent-review.schema.json'),self.contract['independent_review_json_schema'])
        for name in ('collection.schema.json','blind-source.schema.json','independent-review.schema.json'):
            jsonschema.Draft202012Validator.check_schema(read(name))
        jsonschema.Draft202012Validator(read('collection.schema.json')).validate(self.packet)
        jsonschema.Draft202012Validator(read('blind-source.schema.json')).validate(self.blind)

    def test_immutable_manifest_and_contract_provenance(self):
        actual={p.name for p in DATA.iterdir() if p.is_file() and p.name!='build-manifest.json'}
        expected={Path(row['path']).name for row in self.manifest['files']}
        self.assertEqual(actual,expected)
        for row in self.manifest['files']:
            path=ROOT / row['path']
            self.assertEqual(path.parent.resolve(),DATA.resolve())
            raw=path.read_bytes()
            self.assertEqual(len(raw),row['bytes'])
            self.assertEqual(sha(raw),row['raw_sha256'])
            self.assertEqual(row['reviewer_access'],path.name in self.closure['reviewer_files_only'])
        self.assertEqual(sha(canonical(self.manifest['files'])),self.manifest['inventory_canonical_sha256'])
        for stem in ('contract','original_input_schema'):
            self.assertEqual(sha((ROOT / self.meta[stem+'_file']).read_bytes()),self.meta[stem+'_raw_sha256'])
        self.assertEqual(sha(Path(__file__).read_bytes()),self.manifest['test_file_raw_sha256'])
        self.assertEqual(sha((DATA/'author-nominations.parent-only.json').read_bytes()),self.meta['nomination_manifest_sha256'])

    def test_blind_projection_has_exact_inputs_order_ids_and_hashes(self):
        self.assertEqual(len(self.packet['records']),len(self.blind['records']))
        self.assertEqual(self.closure['source_packet_path'],self.meta['blind_packet'])
        self.assertEqual(sha((DATA/self.meta['source_packet']).read_bytes()),self.closure['canonical_packet_raw_sha256'])
        self.assertEqual(sha((DATA/self.meta['blind_packet']).read_bytes()),self.closure['source_packet_raw_sha256'])
        for i,(source,view,entry) in enumerate(zip(self.packet['records'],self.blind['records'],self.closure['records'])):
            self.assertEqual(view,{'example_id':source['example_id'],'input':source['input']})
            self.assertEqual(entry['example_id'],view['example_id'])
            self.assertEqual(entry['root_id'],source['declared_lineage_id'])
            self.assertEqual(entry['source_record_path'],f'/records/{i}')
            self.assertEqual(entry['source_record_json_sha256'],sha(canonical(view)))
            self.assertEqual(entry['source_input_json_sha256'],sha(canonical(view['input'])))
            self.assertEqual(entry['canonical_record_json_sha256'],sha(canonical(source)))
            self.assert_span(entry['whole_utterance_source_span'],self.blind)
            self.assertEqual(entry['whole_utterance_source_span']['text'],view['input']['utterance']['text'])

    def test_full_group_closure_and_alias_edges(self):
        sources={r['example_id']:r for r in self.packet['records']}
        roots={r['root_id']:r for r in self.audit['roots']}
        members=[m for r in self.closure['roots'] for m in r['members']]
        self.assertEqual(Counter(members),Counter(sources.keys()))
        self.assertEqual(set(roots),{r['root_id'] for r in self.closure['roots']})
        for group in self.closure['roots']:
            self.assertEqual(group['members'],roots[group['root_id']]['members'])
            for m in group['members']:
                self.assertEqual(sources[m]['declared_lineage_id'],group['root_id'])
        expected={(r['members'][0],m) for r in roots.values() for m in r['members'][1:]}
        actual={(e['left_example_id'],e['right_example_id']) for e in self.audit['within_root_alias_edges']}
        self.assertEqual(expected,actual)
        for a,b in actual:
            self.assertEqual(sources[a]['author_provenance'],sources[b]['author_provenance'])

    def test_requested_family_inventory_is_not_class_support(self):
        families=defaultdict(list)
        for r in self.audit['roots']:
            families[r['requested_family_kind']].append(r)
        self.assertEqual(len(families['administrative']),12)
        self.assertTrue(all(2 <= len(r['members']) <= 3 for r in families['administrative']))
        self.assertEqual(len(families['date']),8)
        self.assertTrue(all(len(r['members'])==3 for r in families['date']))
        self.assertEqual(len({r['source_neutral_template']['skeleton'] for r in families['date']}),8)
        count=self.meta['authored_counts']
        self.assertEqual(count['total_records'],len(self.packet['records']))
        self.assertEqual(count['declared_roots'],len(self.audit['roots']))
        self.assertIn('diagnostics',self.meta['counts_are'])
        self.assertIn('not IID',self.audit['union_state'])

    def test_current_local_facts_have_exact_prior_source_evidence(self):
        for i,row in enumerate(self.packet['records']):
            inp=row['input']
            self.assertEqual(inp['phase'],'post_verified_account')
            self.assertEqual(inp['state_revision'],2)
            self.assertEqual(inp['utterance']['source_turn_id'],inp['turn_id'])
            self.assertNotEqual(inp['question']['spoken_turn_id'],inp['turn_id'])
            indices={t['index'] for t in inp['targets']}
            self.assertTrue(set(inp['question']['target_indices']) <= indices)
            self.assertEqual({p['target_index'] for p in inp['pending']},indices)
            for p in inp['pending']:
                amount=p['components']['amount']
                self.assertEqual(amount['status'],'complete')
                self.assertEqual(len(amount['evidence_refs']),1)
                ref=amount['evidence_refs'][0]
                self.assertNotEqual(ref['source_turn_id'],inp['turn_id'])
                self.assert_span(ref,self.packet)
                self.assertEqual(ref['text'],str(amount['value'])+' units')
                self.assertIn('have not supplied any dates',ref['source_text'])
                self.assertEqual(p['components']['date']['status'],'absent')
                self.assertIsNone(p['components']['date']['value'])
                self.assertEqual(p['components']['date']['evidence_refs'],[])
            self.assertEqual(inp['policy_hash'],sha(self.meta['policy_hash_fictional_preimage'].encode()))
            self.assertEqual(inp['api_hash'],sha(self.meta['api_hash_fictional_preimage'].encode()))

    def test_source_supervision_absent_and_blind_handoff_segregated(self):
        forbidden={'primary_label','primary_observed','completion','completion_observed','polarity','presence','candidate_role',
                   'expected','oracle','y','ground_truth','prediction','predictions','score','author_nomination_only','normalized_value',
                   'target_scope_observed','maximal_boundary_observed','rationale','date_candidates'}
        for packet in (self.packet,self.blind):
            self.assertFalse(set(keys(packet)) & forbidden)
        for row in self.blind['records']:
            self.assertEqual(set(row),{'example_id','input'})
        self.assertNotIn('collection_axis',set(keys(self.blind)))
        self.assertNotIn('author_provenance',set(keys(self.blind)))
        allowed=set(self.closure['reviewer_files_only'])
        self.assertEqual(len(allowed),5)
        self.assertFalse(any('parent-only' in x or x.endswith('.py') for x in allowed))
        self.assertNotIn(self.meta['source_packet'],allowed)
        instructions=(DATA/'REVIEW_INSTRUCTIONS.txt').read_text(encoding='utf-8')
        self.assertFalse(re.search(r'\b(?:desired|expected)\s+(?:negative|positive|complete|unfinished)',instructions,re.I))
        self.assertNotIn('author_nomination_only',canonical(self.closure).decode('utf-8'))

    def test_privacy_surface_and_source_scope(self):
        sensitive_keys={'customer_id','account_id','account_number','first_name','last_name','date_of_birth','dob','phone','phone_last4','pin','email','credentials'}
        for row in self.packet['records']:
            inp=row['input']
            self.assertFalse(set(keys(inp)) & sensitive_keys)
            self.assertNotEqual(inp['phase'],'security')
            self.assertNotEqual(inp['question']['role'],'security')
            self.assertIsNone(inp['question'].get('security_field'))
            self.assertEqual(inp['spoken_offers'],[])
            self.assertIsNone(inp['active_readback'])
            surfaces=[inp['utterance']['text'],inp['question']['text']]
            surfaces += [ref['source_text'] for p in inp['pending'] for ref in p['components']['amount']['evidence_refs']]
            for text in surfaces:
                self.assertFalse(re.search(r'\b(?:date of birth|phone|password|PIN|passport|social security|customer ID|account number)\b',text,re.I))
                self.assertFalse(re.search(r'\b\d{7,}\b|\b\d{4}-\d{2}-\d{2}\b|[\w.+-]+@[\w.-]+',text))
            self.assertEqual({t['product_id'] for t in inp['targets']},{'generic-card','generic-plan'})
        for field in ('forbidden_source_contents_read','detector_or_predictions_run','new_dev_or_holdout_read','admission_review_adjudication_or_fit_performed'):
            self.assertFalse(self.meta[field])
        self.assertFalse(self.meta['nonce_is_secret'])
        self.assertEqual(self.meta['source_interface'],'finite authored text candidate interface')

    def test_opaque_provenance_identifiers_and_train_only(self):
        ids=set()
        for row in self.packet['records']:
            self.assertRegex(row['example_id'],r'^e-[0-9a-f]{24}$')
            self.assertRegex(row['declared_lineage_id'],r'^r-[0-9a-f]{24}$')
            self.assertNotIn(row['example_id'],ids)
            ids.add(row['example_id'])
            self.assertEqual(row['author_provenance']['author_id'],self.meta['author_id'])
            self.assertTrue(row['author_provenance']['fictional_origin'])
            for key in ('recipe_id','template_skeleton_id','scenario_family_id','source_family_id'):
                self.assertRegex(row['author_provenance'][key],r'^[gkfu]-[0-9a-f]{24}$')
        for item in (self.packet,self.blind,self.closure,self.manifest):
            self.assertEqual(item['split'],'train')

    def test_source_neutral_fingerprints_and_duplicate_audit(self):
        roots={r['root_id']:r for r in self.audit['roots']}
        records={r['example_id']:r for r in self.packet['records']}
        for entry in self.audit['records']:
            root=roots[entry['root_id']]
            self.assertEqual(entry['source_neutral_template_sha256'],sha(canonical(root['source_neutral_template'])))
            self.assertEqual(entry['normalized_backbone_sha256'],sha(entry['normalized_backbone'].encode()))
            self.assertEqual(entry['utterance_raw_utf8_sha256'],sha(records[entry['example_id']]['input']['utterance']['text'].encode()))
            neutral=canonical(root['source_neutral_template']).decode()
            self.assertNotIn(self.meta['author_id'],neutral)
            self.assertNotIn(self.meta['author_root_nonce'],neutral)
            self.assertNotIn(root['root_id'],neutral)
            self.assertEqual(entry['source_neutral_ancestor_aliases'],root['source_neutral_template']['ancestor_aliases'])
        expected=[]
        for key in ('utterance_raw_utf8_sha256','normalized_backbone_sha256','source_neutral_semantic_input_sha256'):
            groups=defaultdict(list)
            for row in self.audit['records']: groups[row[key]].append(row['example_id'])
            expected.extend(dict(key=key,digest=k,members=v) for k,v in groups.items() if len(v)>1)
        self.assertEqual(expected,self.audit['exact_duplicate_checks_before_union'])

    def test_shared_constructions_remain_potential_aliases_before_union(self):
        expected=set()
        roots=self.audit['roots']
        for i,left in enumerate(roots):
            lrows=[r for r in self.audit['records'] if r['root_id']==left['root_id']]
            for right in roots[i+1:]:
                shared=set(left['source_neutral_template']['ancestor_aliases']) & set(right['source_neutral_template']['ancestor_aliases'])
                rrows=[r for r in self.audit['records'] if r['root_id']==right['root_id']]
                ratio=max(SequenceMatcher(None,a['normalized_backbone'],b['normalized_backbone']).ratio() for a in lrows for b in rrows)
                if shared or ratio>=0.72: expected.add((left['root_id'],right['root_id']))
        actual={(r['left_root_id'],r['right_root_id']) for r in self.audit['potential_cross_root_aliases']}
        self.assertEqual(expected,actual)
        self.assertTrue(actual)
        self.assertTrue(all('not_independent_support' in e['status'] for e in self.audit['potential_cross_root_aliases']))
        self.assertIn('unknown',self.audit['cross_source_checks'])
        self.assertIn('different nonce/author/path never establishes independence',self.audit['cross_author_rule'])

    def test_private_nominations_bind_exact_sources_without_becoming_reviews(self):
        nom=read('author-nominations.parent-only.json')
        self.assertEqual(nom['source_packet_raw_sha256'],self.closure['canonical_packet_raw_sha256'])
        self.assertEqual(nom['blind_packet_raw_sha256'],self.closure['source_packet_raw_sha256'])
        self.assertEqual(Counter(r['example_id'] for r in nom['records']),Counter(r['example_id'] for r in self.packet['records']))
        for row in nom['records']:
            self.assertTrue(row['not_ground_truth'])
            self.assertEqual(row['reviewer_access'],'exclude')
            if 'author_span_nomination' in row:
                self.assert_span(row['author_span_nomination'],self.packet)
                i=int(row['author_span_nomination']['raw_field_path'].split('/')[2])
                known={t['index'] for t in self.packet['records'][i]['input']['targets']}
                self.assertTrue(set(row['author_target_nomination']) <= known)
                self.assertEqual(row['reference_and_normalization'],'unassessed; no dated anchor supplied; no normalized value')
        # No empty review, fabricated consensus, or annotations are authored.
        self.assertFalse(list(DATA.glob('*reviewer*.json')))
        self.assertFalse(list(DATA.glob('*adjudication*.json')))

    def test_unicode_source_offsets_are_distinct_from_utf8_bounds(self):
        nominations=read('author-nominations.parent-only.json')['records']
        spans=[n['author_span_nomination'] for n in nominations if 'author_span_nomination' in n]
        self.assertTrue(any(s['char_start'] != s['utf8_byte_start'] for s in spans))
        for s in spans:
            self.assert_span(s,self.blind)
        self.assertTrue(any(len(r['input']['utterance']['text']) != len(r['input']['utterance']['text'].encode('utf-8'))
                            for r in self.packet['records']))

    def test_analysis_report_binds_real_counts_and_artifacts(self):
        report=json.loads((ROOT/'analysis/night-semantic-v6-peer-extension.json').read_text(encoding='utf-8'))
        self.assertEqual(report['counts'],self.meta['authored_counts'])
        self.assertEqual(report['source_packet_raw_sha256'],self.closure['canonical_packet_raw_sha256'])
        self.assertEqual(report['blind_packet_raw_sha256'],self.closure['source_packet_raw_sha256'])
        self.assertEqual(report['review_closure_raw_sha256'],sha((DATA/'review-closure.json').read_bytes()))
        self.assertEqual(report['build_manifest_raw_sha256'],sha((DATA/'build-manifest.json').read_bytes()))
        self.assertEqual(report['inventory_canonical_sha256'],self.manifest['inventory_canonical_sha256'])
        self.assertEqual(report['duplicate_diagnostics']['exact_duplicate_groups'],len(self.audit['exact_duplicate_checks_before_union']))
        self.assertEqual(report['duplicate_diagnostics']['potential_cross_root_alias_pairs'],len(self.audit['potential_cross_root_aliases']))
        self.assertEqual(report['reviewed_records'],0)
        self.assertEqual(report['adjudicated_records'],0)
        self.assertIn('unknown',report['eligible_canonical_class_support'])

if __name__=='__main__':
    unittest.main()
