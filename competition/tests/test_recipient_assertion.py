"""Source parser laws with dynamic subjects, not bank/workflow qualification."""
import ast
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recipient_assertion as module
from recipient_assertion import recipient_assertion as parse


class RecipientAssertionTests(unittest.TestCase):
    def test_parameterized_names_are_current_assertions_not_anywhere_matches(self):
        subjects = [('Nila', 'Voss', 'Dr'), ('Éloïse', 'D’Aubigny', 'Prof'),
                    ('İdil', 'Işık', 'Ms'), ('Jean-Luc', 'O’Rourke', 'Mr'),
                    ('Çağdaş', 'Gündüz', 'Dr'), ('Renée', 'Van Buren', 'Mrs')]
        for given, family, title in subjects:
            positives = ["I'm " + given, 'This is '+given+' '+family,
                         'Ben '+given+' '+family, family+' benim, buyurun.',
                         title+' '+family+' speaking.', given+' here.',
                         given+' '+family+' konuşuyor.', "I'm "+family+', '+given]
            for raw in positives:
                with self.subTest(subject=given, raw=raw):
                    out=parse(raw,given,family,title)
                    self.assertEqual(out['decision'],'SELF')
                    self.assertFalse(out['bank_authority'])
                    self.check_spans(raw,out)
            for raw in ('I sent a letter to '+given, 'Have you met '+family+'?',
                        'This paperwork names '+given+' '+family,
                        given+' said he is ready.', 'Which '+given+'?'):
                with self.subTest(raw=raw):self.assertEqual(parse(raw,given,family,title)['decision'],'UNKNOWN')

    def check_spans(self,raw,out):
        for assertion in out['assertions']:
            start,end=assertion['source_span']
            self.assertTrue(0<=start<end<=len(raw))
            self.assertEqual(assertion['text'],raw[start:end])
            self.assertIn(assertion['polarity'],('positive','negative','unknown'))
        if out['decision']=='UNKNOWN':self.assertEqual(out['source_span'],[])
        else:self.assertEqual(len(out['source_span']),2)

    def test_titles_are_dynamic_multilingual_aliases_and_not_title_only(self):
        for title,aliases in [('Prof',('Prof','Professor','Profesör','PROFESÖR')),
                             ('Dr',('Dr.','Doctor','Doktor','DOKTOR')),
                             ('Ms',('Ms','Miss','Hanım')),('Mr',('Mr','Mister','Bey'))]:
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertEqual(parse(alias+' Arslan benim.','Suna','Arslan',title)['decision'],'SELF')
                    self.assertEqual(parse(alias+' speaking.','Suna','Arslan',title)['decision'],'UNKNOWN')
        self.assertEqual(parse('Captain Arslan here.','Suna','Arslan','Captain')['decision'],'SELF')

    def test_apostrophe_hyphen_and_case_normalize_symmetrically(self):
        for spoken in ("I'm Anne-Marie D'Artois", 'I’m Anne‑Marie D’Artois',
                       'I am ANNE–MARIE DʼARTOIS'):
            self.assertEqual(parse(spoken,'Anne-Marie',"D'Artois",'Dr')['decision'],'SELF')
        self.assertEqual(parse('ben idil ışık.','İdil','Işık')['decision'],'SELF')
        self.assertEqual(parse('Ben Şule Gök.','Şule','Gök')['decision'],'SELF')

    def test_quotes_are_separate_from_name_apostrophes(self):
        for quoted in ("'I'm Nila Voss.'", '“Nila Voss benim.”', '‘I am Nila Voss.’'):
            out=parse(quoted,'Nila','Voss')
            self.assertEqual(out['decision'],'UNKNOWN');self.check_spans(quoted,out)
            self.assertTrue(any(a['act']=='quotation' for a in out['assertions']))
        for raw in ("Nila said 'I'm Nila Voss.' I'm her neighbour.",
                    "Nila dün 'Nila Voss benim' dedi. Ben annesiyim."):
            self.assertEqual(parse(raw,'Nila','Voss')['decision'],'OTHER')
        self.assertEqual(parse("O'Rourke speaking.",'Nila',"O'Rourke")['decision'],'SELF')

    def test_denial_is_bound_to_the_recipient_not_every_negation(self):
        for raw in ("No, I'm not Dr Voss.", 'Ben Nila Voss değilim.',
                    'Nila değilim.', "My name isn't Nila Voss."):
            out=parse(raw,'Nila','Voss','Dr')
            self.assertEqual(out['decision'],'OTHER')
            self.assertTrue(any(a['act']=='identity_denial' and a['polarity']=='negative' for a in out['assertions']))
        for raw in ("I'm Nila; I am not Rowan.", "I'm Nila; I am not Nila's brother."):
            self.assertEqual(parse(raw,'Nila','Voss')['decision'],'SELF')

    def test_later_dob_refusal_is_an_independent_act(self):
        refusals=("I won't verify my birthday.", 'doğum tarihimi söylemem.',
                  'I refuse to disclose my date of birth.')
        for refusal in refusals:
            for raw in ('Nila benim; '+refusal, "I'm Nila Voss, but "+refusal,
                        refusal+" I'm Nila Voss."):
                with self.subTest(raw=raw):
                    out=parse(raw,'Nila','Voss')
                    self.assertEqual(out['decision'],'SELF')
                    self.assertTrue(any(a['act']=='dob_refusal' and a['polarity']=='negative' for a in out['assertions']))
                    self.check_spans(raw,out)

    def test_courtesy_suffix_words_are_not_name_components(self):
        for suffix in ('buyurun','efendim','please','thank you','thanks','merhaba'):
            for raw in ('Voss benim, '+suffix+'.', "I'm Nila "+suffix+'.'):
                with self.subTest(raw=raw):self.assertEqual(parse(raw,'Nila','Voss')['decision'],'SELF')

    def test_different_given_name_cannot_be_erased_by_family_collision(self):
        for raw in ('Ben Rowan Voss; Nila için geldim.', "I'm Rowan Voss.",
                    'My name is rowan voss.', "I'm Voss, Rowan."):
            self.assertEqual(parse(raw,'Nila','Voss')['decision'],'OTHER')
        self.assertEqual(parse('Voss benim.','Nila','Voss')['decision'],'SELF')

    def test_no_answer_or_caller_prompt_never_matches_a_name(self):
        for raw in ('[no answer; voicemail: Nila Voss]', "[silence; caller repeats 'Dr Nila Voss?']",
                    'Caller: Nila Voss?', 'Voicemail: Nila Voss speaking.'):
            self.assertEqual(parse(raw,'Nila','Voss','Dr')['decision'],'OTHER')

    def test_unknown_extraction_requires_no_external_state(self):
        # The parser accepts only raw speech and dynamic names; extraction can be
        # absent/unknown without injecting model labels or state into the parser.
        for extraction in (None, {}, {'recipient':'unknown'}):
            out=parse('Profesör Voss benim.','Nila','Voss','Prof')
            self.assertEqual(out['decision'],'SELF')
            self.assertNotIn('verified',out)
            self.assertNotIn('extraction',out)

    def test_postposed_attribution_does_not_leave_a_bare_subject_as_self(self):
        for raw in ("Nila 'I'm Nila Voss' dedi.", "Nila 'I'm Nila Voss'.",
                    'Nila “Nila Voss benim” söyledi.'):
            self.assertEqual(parse(raw,'Nila','Voss')['decision'],'UNKNOWN')
        self.assertEqual(parse("Nila 'I'm Nila Voss' dedi. Ben annesiyim.",'Nila','Voss')['decision'],'OTHER')

    def test_wrong_recipient_and_absence_have_current_negative_spans(self):
        for raw in ('You have the wrong number.', 'Wrong person.', 'Ben değilim.',
                    'Yanlış numara.', 'Nila is away.', 'Nila burada değil.'):
            out=parse(raw,'Nila','Voss')
            self.assertEqual(out['decision'],'OTHER');self.check_spans(raw,out)
        self.assertEqual(parse('Nila is away?','Nila','Voss')['decision'],'UNKNOWN')

    def test_questions_attribution_and_hypotheticals_are_unknown(self):
        for raw in ("I'm Nila?", "Nila says I'm Nila Voss.",
                    "According to the note, I'm Nila Voss.",
                    "If you ask, I'm Nila Voss.", 'Pretend I am Nila Voss.',
                    'Nila? Which Nila?', 'Doktor konuşuyor.'):
            with self.subTest(raw=raw):self.assertEqual(parse(raw,'Nila','Voss','Dr')['decision'],'UNKNOWN')

    def test_common_word_name_in_exact_assertion_is_not_a_verb_blacklist(self):
        self.assertEqual(parse("I'm Said Park.",'Said','Park')['decision'],'SELF')
        self.assertEqual(parse("She said I'm Said Park.",'Said','Park')['decision'],'UNKNOWN')
        self.assertEqual(parse("If asked, I'm Said Park.",'Said','Park')['decision'],'UNKNOWN')

    def test_contradictions_are_retained_without_selecting_a_winner(self):
        for raw in ("I'm Nila; I am not Nila.", "I am not Nila; I'm Nila.",
                    "I'm Nila. I'm her sister."):
            out=parse(raw,'Nila','Voss')
            self.assertEqual(out['decision'],'UNKNOWN')
            self.assertEqual(out['reason'],'CONFLICTING_CURRENT_IDENTITIES')
            self.assertGreaterEqual(len(out['assertions']),2)

    def test_unrelated_clause_and_reported_quote_do_not_manufacture_self(self):
        for raw in ('I am busy; Nila is on the list.', "I'm looking for Nila Voss.",
                    "I am speaking to Nila Voss.", "I'm not only Nila Voss."):
            self.assertNotEqual(parse(raw,'Nila','Voss')['decision'],'SELF')
        self.assertEqual(parse("'I'm Rowan.' I'm Nila Voss.",'Nila','Voss')['decision'],'SELF')

    def test_input_bounds_and_types_produce_explicit_unknown(self):
        for raw,given,family,title in ((None,'Nila','Voss',''), ('x'*16385,'Nila','Voss',''),
                                       ('Nila speaking.','','',''), ('Nila speaking.','x'*257,'Voss','')):
            out=parse(raw,given,family,title)
            self.assertEqual(out['decision'],'UNKNOWN');self.assertFalse(out['bank_authority'])

    def test_exact_inline_source_has_only_allowed_imports_and_no_entrypoint(self):
        source=Path(module.__file__).read_text(encoding='utf8')
        self.assertLess(len(source.encode('utf8')),25000)
        for marker in (chr(123)*2,chr(125)*2):self.assertNotIn(marker,source)
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):self.assertTrue(all(a.name in ('re','json') for a in node.names))
            self.assertNotIsInstance(node,ast.ImportFrom)
        namespace={};exec(compile(source,'inline-recipient','exec'),namespace)
        self.assertEqual(namespace['recipient_assertion']('Nila here.','Nila','Voss')['decision'],'SELF')
        self.assertEqual(namespace['recipient_assertion']('Voss benim, buyurun.','Nila','Voss'),
                         parse('Voss benim, buyurun.','Nila','Voss'))
        json.dumps(namespace['recipient_assertion']('Ben Nila.','Nila','Voss'),allow_nan=False)

    def test_speaking_frames_compose_without_accepting_third_party_or_different_name(self):
        for given,family in [('Éloïse','D’Aubigny'),('Nila','Said'),('İdil','Işık')]:
            for raw in ('Speaking, '+given+' '+family, 'This is '+given+' '+family+' speaking.',
                        "I'm "+given+' here.', 'That is me.', 'This is me.'):
                with self.subTest(raw=raw):self.assertEqual(parse(raw,given,family)['decision'],'SELF')
            for raw in ('This is Other '+family+' speaking.',
                        'If this is '+given+' '+family+' speaking.',
                        'My brother said "This is '+given+' '+family+' speaking".',
                        'That is not me.', 'Speaking, her brother '+given+' '+family):
                with self.subTest(raw=raw):self.assertNotEqual(parse(raw,given,family)['decision'],'SELF')

    def test_specific_identity_denial_and_relation_override_generic_yes(self):
        for given,family in [('İdil','Işık'),('Nila','Voss')]:
            for raw in ('Yes. '+given+' is not me.', 'Yes. I am '+given+' '+family+'’s cousin.',
                        'Yes. I am her cousin.', 'This is '+given+' '+family+', but I am pretending.'):
                with self.subTest(raw=raw):self.assertNotEqual(parse(raw,given,family)['decision'],'SELF')
            self.assertEqual(parse("I'm "+given+' '+family+", but I won't verify my birthday.",given,family)['decision'],'SELF')

    def test_qualified_and_delegated_identity_cannot_reuse_an_opening_yes(self):
        for given,family in [('Nila','Voss'),('İdil','Işık')]:
            for raw in ('This is '+given+' '+family+', but I’m only pretending.',
                        'This is '+given+' '+family+', but I am pretending to be them.',
                        'Yes. '+given+' '+family+' said to answer for him.',
                        'Yes. "I am '+given+' '+family+'".',
                        'Evet. '+given+' '+family+' dedi.'):
                with self.subTest(raw=raw):self.assertNotEqual(parse(raw,given,family)['decision'],'SELF')
            self.assertEqual(parse('I am '+given+' '+family+'. My brother said to call later.',given,family)['decision'],'SELF')


if __name__=='__main__':unittest.main()
