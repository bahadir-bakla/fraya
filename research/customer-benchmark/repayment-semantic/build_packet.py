"""Author a synthetic engineering packet, never fit or evaluate a model.

All scenario/contrast/paraphrase descendants stay in their declared family.
Existing competition cases, actor expectations and public corpus rows are unused.
"""
import json
import hashlib
import pathlib
import re
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
HEADS = ['proposal', 'dispute', 'correction', 'current_affirm', 'current_withdraw', 'uncertain', 'reported_third_party']
DEFS = {
 'proposal': 'Current speaker makes or revises an own payment intention/commitment; completion/value resolution separate. Hypothetical and solely reported commitments are not own proposals.',
 'dispute': 'Current speaker contests liability, ownership, amount or a claimed payment/account fact; may coexist with willingness to pay.',
 'correction': 'Current speaker replaces/retracts an interpretation or prior term; not merely mentioning somebody else corrected something.',
 'current_affirm': 'Current affirmative response to an observed question/readback/request, including recipient/admin scope. It is not a financial authorization label.',
 'current_withdraw': 'Current retraction/suspension of previously expressed permission or arrangement. First refusal without a prior grant is separate and is not this label.',
 'uncertain': 'Conditional, hypothetical, tentative, incomplete or referentially ambiguous relevant content. Does not mechanically blank complete unrelated acts.',
 'reported_third_party': 'Speaker attributes relevant statements/intention to another person or institution rather than adopting all of them as own current intent.'
}

# Each tuple: split, conservative scenario family, observable previous utterances,
# scope metadata for diagnostics ONLY, positive labels, four sibling variants.
FAMILIES = [
 ('TRAIN','T01-future-pay', [('SYSTEM','What would you like to do about the balance?')], 'new_payment_proposal', ['proposal'], ["I will pay part of the balance after my next payday.","I plan to make a payment when my wages arrive.","I intend to pay something toward this balance next month.","My next step is to make a payment after I receive my salary."]),
 ('TRAIN','T02-liability-contest',[('SYSTEM','The balance is shown against your account.')], 'liability_dispute',['dispute'],["That debt does not belong to me.","I dispute being responsible for this balance.","I never took out the account you are describing.","The liability is attached to the wrong person."]),
 ('TRAIN','T03-change-proposal',[('USER','I will pay the whole balance.'),('SYSTEM','You proposed paying the whole balance.')], 'new_payment_terms',['proposal','correction'],["Actually, make that a partial payment.","Change my proposal to paying only part of it.","I meant a smaller payment rather than the full balance.","Please replace my earlier plan with a part payment."]),
 ('TRAIN','T04-benign-negation-affirm',[('SYSTEM','Are the payment terms I just read back the terms you mean?')], 'payment_readback',['current_affirm'],["Yes, no problem.","Yes, I do not mind those terms.","Correct; I have no objection to that readback.","Absolutely, nothing in that readback needs changing."]),
 ('TRAIN','T05-revoke-grant',[('USER','You may record this arrangement.'),('SYSTEM','I have not submitted it yet.')], 'prior_payment_permission',['current_withdraw'],["Withdraw my permission to record it.","I take back that approval; do not submit it.","My earlier authorization is revoked.","Cancel my consent to that submission."]),
 ('TRAIN','T06-contingent-funding',[('SYSTEM','Can you offer a payment plan?')], 'conditional_payment',['uncertain'],["If my refund arrives, I might be able to pay.","A payment may be possible provided the refund comes through.","Perhaps I could pay, depending on whether I get that refund.","I cannot promise yet; the refund would have to arrive first."]),
 ('TRAIN','T07-other-payer',[('SYSTEM','What has been discussed about the balance?')], 'third_party_report',['reported_third_party'],["My brother said he would pay it.","The person offering to pay is my brother, not me.","I am reporting my brother's promise to make the payment.","It was my brother who committed to paying this balance."]),
 ('TRAIN','T08-report-own-adoption',[('SYSTEM','Who intends to make a payment?')], 'own_and_reported',['reported_third_party','proposal'],["My partner offered to help, and I will pay my share.","My partner said they could contribute; I also commit to a payment myself.","They promised some help, but my own plan is to pay part of the balance.","I heard their offer to contribute and I intend to make my own payment too."]),
 ('TRAIN','T09-pay-under-dispute',[('SYSTEM','What is your position on this balance?')], 'dispute_and_proposal',['dispute','proposal'],["I dispute the charge, but I will make a partial payment.","The amount is wrong; nevertheless I plan to pay part of it.","I challenge this balance and still intend to make a payment.","Although I deny owing the full sum, I will pay the part I accept."]),
 ('TRAIN','T10-correct-and-affirm',[('SYSTEM','So you mean the full balance this month?')], 'corrected_readback',['correction','current_affirm','proposal'],["Yes to a payment this month, but only part of the balance.","The timing is right; change the payment to a partial one.","I agree about this month, and I meant a smaller payment.","Correct on the month, but replace the full sum with a part payment."]),
 ('TRAIN','T11-recipient-affirm',[('SYSTEM','Am I speaking to the account holder?')], 'recipient_identity',['current_affirm'],["Yes, you are speaking to me.","That is right, I am the person you asked for.","Correct, this is the account holder speaking.","You have reached the person named on the account."]),
 ('TRAIN','T12-negated-stop',[('SYSTEM','Would you like to end this call?')], 'information_request',[],["I am not asking you to stop calling; I need the balance explained.","I do not want the call ended; please explain the charge.","Stopping the conversation is not my request. Tell me what the balance means.","Do not interpret my question as a request to end contact; I want information."]),
 ('TRAIN','T13-incomplete-own-date',[('SYSTEM','What payment are you proposing?')], 'unfinished_payment_date',['proposal','uncertain'],["I will pay on...","My payment date will be, um...","I intend to make the payment when...","I can commit to a payment, and the day is..."]),
 ('TRAIN','T14-incomplete-correction',[('SYSTEM','Do you mean the payment on the date I read back?')], 'unfinished_date_correction',['correction','uncertain'],["No, the date should be...","That date is wrong; I meant...","Replace the day you read with, uh...","Not that day, the one I intended was..."]),
 ('TRAIN','T15-first-refusal',[('SYSTEM','Would you like to accept this arrangement?')], 'first_refusal',[],["I refuse that arrangement.","I am not agreeing to the proposed plan.","I reject the payment offer you have just made.","That arrangement is not acceptable to me."]),
 ('TRAIN','T16-hold-after-approval',[('USER','Go ahead with recording the plan.'),('SYSTEM','The submission is still pending.')], 'pause_previous_permission',['current_withdraw'],["Pause that submission while I check the details.","Hold off on recording it for now.","Do not proceed yet; I need to check something.","Suspend my go-ahead until I have checked the plan."]),
 ('TRAIN','T17-quoted-promise',[('SYSTEM','Did you just make a payment commitment?')], 'quoted_third_party',['reported_third_party'],["The words 'I will pay' were a quotation from my sister.","I was quoting my sister when I mentioned a promise to pay.","That payment promise was my sister's statement, not my own.","Please treat those payment words as a report of what my sister said."]),
 ('TRAIN','T18-admin-affirm',[('SYSTEM','May I explain what this call is about?')], 'administrative_explanation',['current_affirm'],["Sure, explain the purpose of the call.","Yes, you may explain that.","Go ahead with the explanation.","I agree to hearing the reason for this conversation."]),
 ('CAL','C01-installment-offer',[('SYSTEM','How do you propose addressing the outstanding balance?')], 'new_payment_proposal',['proposal'],["I propose settling it in installments.","My offer is to repay through several installments.","I am putting forward an installment repayment plan.","I would like to arrange repayment in installments."]),
 ('CAL','C02-transaction-denial',[('SYSTEM','This purchase appears on your statement.')], 'transaction_dispute',['dispute'],["I did not make that purchase.","The purchase you mentioned is not mine.","I contest the transaction on that statement.","Someone else made the transaction you are describing."]),
 ('CAL','C03-replace-frequency',[('USER','I propose monthly payments.'),('SYSTEM','You suggested paying monthly.')], 'proposal_frequency_change',['proposal','correction'],["Amend the schedule to weekly payments instead.","Use a weekly schedule in place of monthly payments.","The frequency I want is weekly, not monthly.","I revise that proposal to payments every week."]),
 ('CAL','C04-readback-assent',[('SYSTEM','Does the arrangement just described reflect your payment offer?')], 'payment_readback',['current_affirm'],["It does reflect my offer.","You have described my offer accurately.","The readback matches what I proposed.","That account of my arrangement is accurate."]),
 ('CAL','C05-reconsider-approved',[('USER','You can proceed with this plan.'),('SYSTEM','I am waiting before submitting it.')], 'retract_previous_permission',['current_withdraw'],["I have reconsidered; my go-ahead no longer applies.","I am rescinding the approval I gave earlier.","My permission to proceed is no longer in effect.","I retract the agreement I just gave you."]),
 ('CAL','C06-reported-tentative',[('SYSTEM','Has anyone discussed helping with repayment?')], 'reported_conditional',['reported_third_party','uncertain'],["A relative mentioned they might help if funds become available.","I was told that a relative could possibly contribute.","Their offer to help depended on money becoming available.","The relative's comment was a possibility, not a firm commitment."]),
 ('HELDOUT','H01-split-obligations',[('SYSTEM','What do you intend for the two balances?')], 'two_payment_proposals',['proposal'],["I intend to reduce each balance with a separate payment.","My plan is to make one payment toward each obligation.","I will contribute separately to both balances.","I commit to paying something against each of those balances."]),
 ('HELDOUT','H02-dispute-adjustment',[('SYSTEM','An adjustment has been added to the balance.')], 'adjustment_dispute',['dispute'],["I challenge the added adjustment.","I do not accept the adjustment as a valid debt.","The additional balance item is being disputed by me.","I contest your account of why that adjustment is owed."]),
 ('HELDOUT','H03-correct-linguistic-reference',[('USER','I offered a payment after the first statement.'),('SYSTEM','You referred to the first statement.')], 'corrected_reference',['proposal','correction'],["By first statement I meant the next statement to arrive.","Interpret my reference as the upcoming statement, not the old one.","I am correcting which statement triggers my payment offer.","The statement in my offer is the one still to come."]),
 ('HELDOUT','H04-name-spelling-assent',[('SYSTEM','Is the spelling of your name that I read out correct?')], 'recipient_name',['current_affirm'],["The spelling you read is correct.","You have spelled my name properly.","That spelling matches my name.","I confirm the spelling, yes."]),
 ('HELDOUT','H05-approval-explicit-end',[('USER','You have my permission to log this plan.'),('SYSTEM','Nothing has been logged yet.')], 'end_previous_permission',['current_withdraw'],["That permission ends now.","The approval to log my plan is terminated.","I revoke the previously given go-ahead to log it.","You no longer have my approval for logging this plan."]),
 ('HELDOUT','H06-reported-dispute-modal',[('SYSTEM','What did the other account holder tell you?')], 'reported_dispute_uncertain',['reported_third_party','uncertain'],["They said they may challenge the balance, but have not decided.","Their possible dispute was only something they were considering.","I heard them speculate about contesting the balance.","The other holder was unsure whether they would dispute it."])
]

# Conservatively union repeated whole authorization-retraction/readback scaffolds,
# even when their wording differs. Those aliases are TRAIN descendants, never
# independent calibration/heldout roots. New split roots differ in scope/act graph.
ALIASES={'C04-readback-assent':'T04-benign-negation-affirm','C05-reconsider-approved':'T05-revoke-grant','H05-approval-explicit-end':'T05-revoke-grant'}
FAMILIES += [
 ('CAL','C07-abandon-own-plan',[('USER','My intention is to repay in installments.'),('SYSTEM','You have described a repayment intention.')], 'own_plan_retraction',['current_withdraw'],["I am abandoning that repayment intention.","I no longer plan to carry out the installments I proposed.","The repayment intention I expressed is no longer my plan.","I withdraw my own proposal to repay in installments."]),
 ('CAL','C08-timing-only-assent',[('SYSTEM','Ignoring the amount for now, did I hear the timing of your offer correctly?')], 'payment_timing_component',['current_affirm'],["You heard the timing correctly.","The timing alone is what I am confirming.","Your understanding of when is accurate.","On that timing question, you are right."]),
 ('HELDOUT','H07-contact-permission-retraction',[('USER','You can send me information by message.'),('SYSTEM','You allowed informational messages.')], 'contact_permission',['current_withdraw'],["Remove my permission for those messages.","I no longer permit informational messages to be sent.","My permission to receive those messages has ended.","Stop relying on my previous agreement to receive messages."])
]

def digest(raw): return hashlib.sha256(raw).hexdigest()
def save(name, obj):
    p=HERE/name
    raw=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with p.open('xb') as f: f.write(raw)
    return {'path':name,'bytes':len(raw),'sha256':digest(raw)}
def normalized(s): return re.sub(r'\W+',' ',s.casefold()).strip()

def main():
    rows=[]; ancestry=[]
    for authored_split,family,previous,scope,positive,variants in FAMILIES:
        canonical=ALIASES.get(family,family);split='TRAIN' if family in ALIASES else authored_split
        ancestry.append({'family_id':family,'canonical_group':canonical,'authored_split':authored_split,'split':split,'origin':'synthetic_single_author_engineering','descendants':[family+':v'+str(i) for i in range(1,5)],'closure':'all supplied paraphrases and contrasts in this scenario; explicit repeated-scaffold unions; no independent root inflation'})
        for i,text in enumerate(variants,1):
            inp={'previous_utterances':[{'speaker':role,'text':p} for role,p in previous], 'current_utterance':{'speaker':'USER','text':text}}
            rows.append({'record_id':family+':v'+str(i),'family_id':family,'group_id':canonical,'split':split,'source':'authorized_synthetic_engineering_v1','input':inp,'labels':{h:int(h in positive) for h in HEADS},'known_mask':{h:True for h in HEADS},'annotation_metadata_not_features':{'scope':scope,'author':'single_design_author','independently_adjudicated':False,'bank_authority':False,'completion_or_value_targets':'UNTRAINED_UNKNOWN'},'input_sha256':digest(json.dumps(inp,sort_keys=True,separators=(',',':')).encode())})
    # The uncertainty axis can be known while ownership of a bare assent is not.
    # These contrasts are descendants of existing TRAIN families, not new groups.
    contrasts=[('T18-admin-affirm','Okay.',['uncertain'],['current_affirm']),('T07-other-payer','She says I should agree, but I have not decided.', ['reported_third_party','uncertain'],[])]
    for n,(family,text,pos,unknown) in enumerate(contrasts,1):
        base=next(r for r in rows if r['family_id']==family);r=json.loads(json.dumps(base));r['record_id']=family+':contrast'+str(n);r['input']['current_utterance']['text']=text;r['labels']={h:int(h in pos) for h in HEADS};r['known_mask']={h:h not in unknown for h in HEADS};r['annotation_metadata_not_features']['scope']='ambiguous_or_scoped_contrast';r['input_sha256']=digest(json.dumps(r['input'],sort_keys=True,separators=(',',':')).encode());rows.append(r)
        next(a for a in ancestry if a['family_id']==family)['descendants'].append(r['record_id'])
    ids=[r['record_id'] for r in rows]; assert len(ids)==len(set(ids))
    assert len(FAMILIES)==len(set(f[1] for f in FAMILIES))
    for group in set(r['group_id'] for r in rows):assert len(set(r['split'] for r in rows if r['group_id']==group))==1
    # Exact input/current-only aliases across splits are conservatively forbidden.
    by={}; current={}
    for r in rows:
        for key,index in [(r['input_sha256'],by),(normalized(r['input']['current_utterance']['text']),current)]:
            if key in index: assert index[key]==r['split'], 'cross-split alias'
            index[key]=r['split']
    outputs={}
    for split in ['TRAIN','CAL','HELDOUT']:
        selected=[r for r in rows if r['split']==split]; name=split.lower()+'.jsonl'; raw=('\n'.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':')) for r in selected)+'\n').encode()
        with (HERE/name).open('xb') as f:f.write(raw)
        outputs[name]={'bytes':len(raw),'sha256':digest(raw),'rows':len(selected),'source_families':len(set(r['family_id'] for r in selected)),'canonical_groups':len(set(r['group_id'] for r in selected)),'positive_rows':{h:sum(r['labels'][h] and r['known_mask'][h] for r in selected) for h in HEADS},'positive_groups':{h:len(set(r['group_id'] for r in selected if r['labels'][h] and r['known_mask'][h])) for h in HEADS},'unknown_elements':sum(not m for r in selected for m in r['known_mask'].values())}
    outputs['ancestry.json']=save('ancestry.json',ancestry)
    outputs['alias-unions.json']=save('alias-unions.json',{'aliases':ALIASES,'reason':'Repeated complete readback/authorization-revocation scenario scaffolds conservatively joined across original author nominations before any fit; all members assigned TRAIN.'})
    outputs['label-spec.json']=save('label-spec.json',{'version':1,'heads':HEADS,'definitions':DEFS,'feature_allowlist':['input.previous_utterances[].speaker','input.previous_utterances[].text','input.current_utterance.speaker','input.current_utterance.text'],'scope':'semantic proposals only; affirmative includes admin/identity and never bank permission; model scores cannot authenticate input or authorize any bank write','multi_label':True,'unknown_mask':'False means unlabelled for this head, NOT negative. Numeric/date/target resolution and authority heads remain UNKNOWN.','negative_negation':'I am not asking you to stop is not a withdrawal; scoped no/not must not blank unrelated acts.','reported_scope':'Third-party reports do not imply a current own promise or consent.'})
    sanity=[
      {'id':'S01','previous':'You proposed160 for balance alpha on14 May.','current':'Change alpha to290 on22 May; keep balance beta as it was.','expected_labels':['proposal','correction'],'expected_guard':'new terms cannot confirm old160/14 May readback; beta unaffected'},
      {'id':'S02','previous':'Can I record160 for alpha and290 for beta?','current':'Yes to alpha, but do not record beta.','expected_labels':['current_affirm'],'expected_guard':'affirmative scope alpha only; beta first refusal unless independently prior-authorized; no global consent'},
      {'id':'S03','previous':'You gave permission to record alpha and beta.','current':'Withdraw permission for beta; alpha can stay.','expected_labels':['current_withdraw','current_affirm'],'expected_guard':'withdrawal scope beta; deterministic graph owns eligibility and execution'},
      {'id':'S04','previous':'Are you the named recipient?','current':'Yes, that is my name.','expected_labels':['current_affirm'],'expected_guard':'identity assent never confirms a payment'},
      {'id':'S05','previous':'We are discussing alpha.','current':'My friend said they would pay290; I am only asking a question.','expected_labels':['reported_third_party'],'expected_guard':'no own payment commitment; no quantity authorizes transaction'},
      {'id':'S06','previous':'You described160 for alpha.','current':'I might offer290 if I get paid, but I have not agreed.','expected_labels':['uncertain'],'expected_guard':'conditional revised possibility is not a current confirmed transaction'}
    ]
    outputs['sanity-retained.json']=save('sanity-retained.json',{'status':'authored diagnostic, explicitly exposed; not training/calibration/heldout gold','toy_facts':'Invented amounts/dates/products solely for general scope checks, not finalbrief constants','cases':sanity})
    manifest={'version':1,'status':'ready_for_exploratory_multilabel_CPU_fit_not_qualified','source':'synthetic authored task data; no competition actor/expected/public case or external corpus rows copied','labels':'single_author_engineering_not_human_or_independent_gold','total_rows':len(rows),'source_families':len(FAMILIES),'canonical_groups':len(set(r['group_id'] for r in rows)),'outputs':outputs,'group_policy':'scenario family includes its paraphrases/contrast descendants; explicit scaffold aliases united before fit; canonical group never spans splits; exact current/input aliases checked. Semantic paraphrase independence is NOT proven; conservative future union may collapse groups. This authored heldout is known to its author, has no evaluated metrics and is not a blind safety qualification set.','split_assignment':'explicit pre-fit registry and alias unions, not random row split','calibration_role':'C01/C03/C07 temperature-fit groups; C02/C06/C08 threshold-selection groups; do not mix roles or invent independent head support','models_trained':0,'metrics_read':0,'bank_permission_gold':False,'auxiliary_SGD':'Optional TRAIN publisher act labels require separate masked head. Never map generic AFFIRM/NEGATE to any financial label. No SGD rows included in this packet.','reference_quarantine':'Tau reference-only benchmarks are excluded; existing official competition expectations/actors unchanged','authoring_source_sha256':digest(pathlib.Path(__file__).read_bytes())}
    save('manifest.json',manifest)
    save('validation.json',{'structural_checks':{'unique_record_ids':True,'family_single_split':True,'exact_input_crosssplit_aliases':0,'normalized_current_crosssplit_aliases':0,'seven_binary_labels_and_boolean_masks':all(set(r['labels'])==set(HEADS) and all(type(v) is int and v in (0,1) for v in r['labels'].values()) and all(type(v) is bool for v in r['known_mask'].values()) for r in rows),'no_authority_labels':True},'semantic_checks':'author assertions, independently unreviewed; no model evaluation','rows':len(rows),'families':len(FAMILIES)})
    print(json.dumps({'rows':len(rows),'families':len(FAMILIES),'outputs':{k:v for k,v in outputs.items() if k.endswith('.jsonl')}}))

if __name__=='__main__':main()
