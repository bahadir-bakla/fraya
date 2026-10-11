"""Source-first fictional semantic v3 collection and integrity tests.

Build the six NEW collection artifacts with --build. Default invocation only
validates. Writes are restricted to the six named collection files; the two
worker reports are written only by --report. No network, detector, model fit,
platform operation, or mutation of an earlier dataset is performed.
"""
import copy
import hashlib
import json
import math
import re
import sys
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
DEST = ROOT / 'research/customer-benchmark/semantic-v3-collection'
REPORT = ROOT / 'analysis/night-semantic-v3-collection'
FILES = ('primary-supplement-train.json', 'date-train.json', 'date-dev.json',
         'manifest.json', 'label-free-primary-review-packet.json',
         'label-free-date-review-packet.json')
AUTHOR = 'fresh semantic-v3 fictional data author; inherited workhorse fallback; exact model version unavailable'
PROMPT = ('User-authorized new synthetic weak TRAIN/dev semantic-v3 collection: '
          '12 primary root carriers with two paraphrases each, 24 DATE TRAIN roots '
          'and 8 disjoint DEV roots with 2-3 meaning contrasts; source-first Unicode '
          'boundaries, separate completion/resolution/act/predicate axes, full canonical '
          'closure, label-free TRAIN packets, no platform/cloud/keys/customer PII/model fit.')
POLICY_PATH = 'competition-v3/build-the-builder/briefs/brief-a.md'
API_PATH = 'competition-v3/build-the-builder/tools/openapi.json'
TRAIN_PATH = 'research/customer-benchmark/context-semantic-v2-train.json'
DEV_PATH = 'research/customer-benchmark/context-semantic-v2-dev.json'
PACKET_PATH = 'integrations/learned-dialogue/narrow-v3/review-packet.json'
DESIGN_PATH = 'analysis/learned-layer-design.json'
FROZEN_MANIFEST = 'integrations/learned-dialogue/v2-final-data/manifest.json'
SOURCE_PATHS = (DESIGN_PATH, POLICY_PATH,
                'competition-v3/build-the-builder/briefs/brief-b.md', API_PATH,
                'competition-v3/build-the-builder/docs/api.md', TRAIN_PATH,
                DEV_PATH, PACKET_PATH, FROZEN_MANIFEST)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def opaque(kind, source_key, variant_index=None):
    # IDs encode an arbitrary source identity, never a semantic class, label,
    # nomination, date completeness, split, or sampling stratum.
    material='semantic-v3-identity-namespace-20261011:'+source_key
    if variant_index is not None:material+=':'+str(variant_index)
    return 'SV3-'+kind+'-'+sha(material.encode('utf-8'))[:20]


def gid(key):return opaque('G',key)
def eid_for(key,index):return opaque('E',key,index)


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    value = json.loads(Path(path).read_text(encoding='utf-8'),
                       object_pairs_hook=pairs, parse_constant=bad)
    def finite(x):
        if isinstance(x, float) and not math.isfinite(x):
            raise ValueError('Nonfinite number')
        if isinstance(x, dict):
            for v in x.values(): finite(v)
        if isinstance(x, list):
            for v in x: finite(v)
    finite(value)
    return value


def date(surface, completion='complete', resolution='unresolved', *,
         predicate='asserted', act='asserted', target=0, occurrence=0,
         value=None, clause=None, offer=None):
    # Literal author hypotheses. No punctuation/regex/detector labels truth.
    return dict(surface=surface, expression_completion=completion,
                resolution=dict(status=resolution, canonical_date=value,
                                source_offer_slot=offer),
                act_commitment=act, predicate_scope=predicate,
                target_index=target, occurrence=occurrence, clause=clause)


def variant(text, *dates, time=None, correction=None, context=None,
            primary='payment_proposal', secondary=(), act='asserted',
            predicate='asserted', rationale=''):
    return dict(text=text, dates=list(dates), time_completion=time,
                correction=correction, context=context or {}, primary=primary,
                secondary=list(secondary), act_commitment=act,
                predicate_scope=predicate, rationale=rationale)


def root(key, scene, question, variants, *, role='date', phase='payment',
         products=('personal_loan',), existing_ancestors=(), overlap_reason=None):
    return dict(key=key, scene=scene, question=question, variants=variants,
                role=role, phase=phase, products=list(products),
                existing_ancestors=list(existing_ancestors),
                overlap_reason=overlap_reason)


def primary_roots():
    # Base + TWO paraphrases per carrier, not three independent roots.
    # These scenes, utterances and questions were conceived here. They are not
    # imported scenario/customer identities, test constants, or actor scripts.
    return [
        root('P01', 'Envelope budgeting: speaker initiates a concrete allocation from a ring-fenced household envelope.',
             'Can you make the personal loan payment today?', [
            variant('The envelope marked loan is ready: put me down for 286 pounds next Tuesday.'),
            variant('I have set aside a loan envelope; my proposed payment is 286 pounds for next Tuesday.'),
            variant('Next Tuesday I am assigning the 286 pounds in that separate envelope to my loan.')], role='payment'),
        root('P02', 'Customer narrates two deliberately staggered actions rather than accepting a single offered term.',
             'Can you make the card and car loan payments today?', [
            variant('Here is my sequence: clear the card on Wednesday, then send the car loan instalment on Thursday.'),
            variant('My plan has two steps. Wednesday is for clearing the card; Thursday is for the car loan instalment.'),
            variant('I am arranging the card clearance first, on Wednesday, and the car loan instalment a day later.')],
             role='payment', products=('credit_card','car_loan'), existing_ancestors=('CSv2-E-0134',),
             overlap_reason='Conservative shared target-distributive date carrier, despite fresh sequence narration.'),
        root('P03', 'Customer independently assigns proceeds of a specific fictional sale to the full overdue amount.',
             'Can you make the car loan payment today?', [
            variant('The bicycle sale covers the overdue instalment. I am using all of those proceeds to clear it this afternoon.'),
            variant('I am directing the entire bicycle-sale proceeds to the car loan arrears today; that settles the overdue instalment.'),
            variant('My proposal is to clear today’s car loan instalment using everything I received from selling my bicycle.')], role='payment', products=('car_loan',)),
        root('P04', 'Speaker describes their own chosen future bank-transfer action with an explicit amount.',
             'Can you make the loan payment today?', [
            variant('When I open my banking app tonight, the transfer I am making to this loan is 318 pounds.'),
            variant('Tonight’s banking-app task is my 318-pound transfer for this loan; that is what I will send.'),
            variant('I have chosen a transfer of 318 pounds to the loan, and I will make it in the app this evening.')], role='payment'),
        root('P05', 'A speaker contrasts their usual procrastination with a new present intention.',
             'Can you make this loan payment today?', [
            variant('Usually I put this off until payday. This time I am clearing the overdue loan on Monday morning.'),
            variant('I tend to wait for wages, but my plan this time is Monday morning for clearing the loan arrears.'),
            variant('Unlike my usual payday delay, I have decided on Monday morning to pay off this overdue loan amount.')], role='payment'),
        root('P06', 'Independent lower-amount proposal in a negative answer to the actual today question.',
             'Can you make the full personal loan payment today?', [
            variant('Today is out. A payment of 364 pounds from me on Thursday is what I am proposing instead.'),
            variant('Rather than the full sum today, my proposal is 364 pounds on Thursday.'),
            variant('My alternative to today’s full payment is Thursday with 364 pounds.')], role='payment',
             existing_ancestors=('CSv2-E-0050',),
             overlap_reason='Conservative alternative amount/date prospective-payment carrier overlap with giant TRAIN root.'),
        root('P07', 'Self-repair of a freshly volunteered plan, without responding to an agent readback.',
             'Can you make the card payment today?', [
            variant('I am arranging 427 pounds for the card on Tuesday—sorry, Wednesday; Wednesday is my plan.'),
            variant('My card payment will be 427 pounds. I started to say Tuesday, but I mean Wednesday.'),
            variant('For my 427-pound card payment I choose Wednesday; the Tuesday I just mentioned was a mistake.')], role='payment', products=('credit_card',)),
        root('P08', 'A personal pledge distinguishes the speaker’s own act from a quoted adviser suggestion.',
             'Can you make the overdue loan payment today?', [
            variant('My adviser suggested waiting. My own decision is to clear the overdue loan this Friday.'),
            variant('Waiting was the adviser’s idea; I am choosing to pay the loan arrears in full on Friday.'),
            variant('I am committing to Friday for clearing these loan arrears, regardless of the advice to wait.')], role='payment'),
        root('P09', 'Human-transfer request dominates a separately volunteered secondary payment statement.',
             'Can you make the card payment today?', [
            variant('Please get a person on the line now. I have a card payment planned for Wednesday, but I need a person first.', primary='human_request', secondary=('payment_proposal',)),
            variant('I want to speak to someone now; before discussing my Wednesday card payment, connect me to a person.', primary='human_request', secondary=('payment_proposal',)),
            variant('A person, please, before anything else. There is a Wednesday card payment in my plan, but transfer me now.', primary='human_request', secondary=('payment_proposal',))], role='payment', products=('credit_card',)),
        root('P10', 'Hypothetical payment is embedded in an information question, not adopted as a proposal.',
             'Can you make the personal loan payment today?', [
            variant('Suppose somebody paid 296 pounds next Wednesday: would the remainder still be overdue?', primary='information_question', act='question', predicate='hypothetical'),
            variant('Would the balance stay overdue in the hypothetical case of a 296-pound payment next Wednesday?', primary='information_question', act='question', predicate='hypothetical'),
            variant('I am asking what happens if someone sends 296 pounds next Wednesday; does that leave arrears?', primary='information_question', act='question', predicate='hypothetical')], role='payment'),
        root('P11', 'Withdrawal of the speaker’s prior volunteered plan, without a replacement proposal.',
             'Do you want to change your proposed loan payment before any readback?', [
            variant('Withdraw my earlier suggestion entirely. I am no longer putting forward that loan payment.', primary='correction', act='withdrawn', predicate='retracted'),
            variant('I take the proposed loan payment back; there is no replacement proposal from me.', primary='correction', act='withdrawn', predicate='retracted'),
            variant('Please discard what I suggested for the loan. I retract it without suggesting anything else.', primary='correction', act='withdrawn', predicate='retracted')], role='payment'),
        root('P12', 'Negated payment predicate is followed by the speaker’s actual balance question.',
             'Can you make the overdue car loan payment today?', [
            variant('I am not saying I will pay the car loan next Monday. My question is how you calculated the overdue amount.', primary='information_question', act='question', predicate='negated'),
            variant('How was the car loan arrears figure worked out? My words about next Monday were not a promise to pay.', primary='information_question', act='question', predicate='negated'),
            variant('No payment commitment for Monday is coming from me; I want an explanation of the car loan arrears calculation.', primary='information_question', act='question', predicate='negated')], role='payment', products=('car_loan',))
    ]


def date_train_roots():
    return [
        root('T01','An own wall-calendar entry specifies a named payment day.', 'What date are you putting on your loan calendar?', [
            variant('My loan calendar entry reads 18 November 2026.',date('18 November 2026',resolution='exact_explicit',value='2026-11-18')),
            variant('My loan calendar entry reads the eighteenth of',date('the eighteenth of','unfinished','open_complement')),
            variant('I wrote the eighteenth of November in the loan calendar.',date('the eighteenth of November',resolution='underspecified_year'))]),
        root('T02','A week-long budgeting period contrasts with an unfinished comparison.', 'Which budgeting week do you mean for this loan?', [
            variant('The loan belongs in next week’s budget.',date('next week',resolution='vague_period')),
            variant('The loan belongs in the week after',date('the week after','unfinished','open_complement')),
            variant('I mean the week after next for the loan budget.',date('the week after next',resolution='vague_period'))]),
        root('T03','A date is copied from an invoice’s payment field, never a birthday.', 'What does your invoice say in its payment-date field?', [
            variant('The payment-date field says the third of May.',date('the third of May',resolution='underspecified_year',predicate='quoted',act='reported'),primary='other',act='reported',predicate='quoted'),
            variant('The payment-date field says the third of...',date('the third of','unfinished','open_complement',predicate='quoted',act='reported'),primary='other',act='reported',predicate='quoted'),
            variant('On my invoice the payment date is 3 May 2027.',date('3 May 2027',resolution='exact_explicit',value='2027-05-03',act='reported'),primary='other',act='reported')]),
        root('T04','Callback question answered by the intended person with an unfinished clock time.', 'On which day and at what time should we ring you again?', [
            variant('Reach me on Thursday at...',date('Thursday',resolution='relative_day'),time='unfinished',primary='callback_proposal'),
            variant('Reach me on Thursday at 16:40.',date('Thursday',resolution='relative_day'),time='complete',primary='callback_proposal'),
            variant('Reach me on the day after',date('the day after','unfinished','open_complement'),primary='callback_proposal')],role='callback',phase='callback'),
        root('T05','Same complete ordinal has one, zero, or two admissible prior spoken offer referents.', 'Which of the dates actually spoken do you mean?', [
            variant('Let the twenty-second be the anchor for my loan.',date('the twenty-second',resolution='unique_spoken_offer',offer=0,value='2026-11-22'),context={'offers':['2026-11-22']}),
            variant('Let the twenty-second be the anchor for my loan.',date('the twenty-second',resolution='no_offer_referent'),context={'offers':[]}),
            variant('Let the twenty-second be the anchor for my loan.',date('the twenty-second',resolution='multiple_offer_referents'),context={'offers':['2026-11-22','2026-12-22']})]),
        root('T06','Two product lanes have separately scoped dates.', 'What dates go into the card and loan lanes of your plan?', [
            variant('The card lane is for the morning of...; the loan lane is for Wednesday.',date('the morning of','unfinished','open_complement',target=0,clause='The card lane is for the morning of...'),date('Wednesday',resolution='relative_day',target=1,clause='the loan lane is for Wednesday')),
            variant('The card lane is for Tuesday; the loan lane is for the morning of...',date('Tuesday',resolution='relative_day',target=0,clause='The card lane is for Tuesday'),date('the morning of','unfinished','open_complement',target=1,clause='the loan lane is for the morning of...')),
            variant('The card lane is for Tuesday; the loan lane is for Wednesday.',date('Tuesday',resolution='relative_day',target=0),date('Wednesday',resolution='relative_day',target=1))],products=('credit_card','personal_loan')),
        root('T07','Deposit condition qualifies the predicate, not the completed date phrase.', 'Which date would apply if that deposit clears?', [
            variant('Provided the deposit clears, my payment date is 9 December 2026.',date('9 December 2026',resolution='exact_explicit',value='2026-12-09',predicate='conditional',act='conditional'),predicate='conditional',act='conditional'),
            variant('Provided the deposit clears, my payment date is the ninth of',date('the ninth of','unfinished','open_complement',predicate='conditional',act='conditional'),predicate='conditional',act='conditional'),
            variant('Provided the deposit clears, next month is the payment period.',date('next month',resolution='vague_period',predicate='conditional',act='conditional'),predicate='conditional',act='conditional')]),
        root('T08','A quoted reminder is reported by the customer rather than asserted as their own proposal.', 'What payment date did that reminder quote?', [
            variant('The reminder quoted “the seventh of June”; I have not adopted that plan.',date('the seventh of June',resolution='underspecified_year',predicate='quoted',act='reported'),primary='other',act='reported',predicate='quoted'),
            variant('The reminder quoted “the seventh of”; that is where its sentence stopped.',date('the seventh of','unfinished','open_complement',predicate='quoted',act='reported'),primary='other',act='reported',predicate='quoted'),
            variant('The reminder quoted “next summer”; I am only reporting its wording.',date('next summer',resolution='vague_period',predicate='quoted',act='reported'),primary='other',act='reported',predicate='quoted')]),
        root('T09','Rejected date versus open rejected complement; rejection does not imply incompletion.', 'Which suggested payment date are you rejecting?', [
            variant('Saturday is not a payment date I am accepting.',date('Saturday',resolution='relative_day',predicate='negated',act='denied'),primary='payment_refusal',act='denied',predicate='negated'),
            variant('The afternoon of is not a payment date I am accepting.',date('The afternoon of','unfinished','open_complement',predicate='negated',act='denied'),primary='payment_refusal',act='denied',predicate='negated'),
            variant('I am rejecting the payment date 12 December 2026.',date('12 December 2026',resolution='exact_explicit',value='2026-12-12',predicate='negated',act='denied'),primary='payment_refusal',act='denied',predicate='negated')]),
        root('T10','A nonterminal hesitation is followed by an explicit same-turn completed sibling.', 'What date survived your hesitation just now?', [
            variant('For the loan, on the... let me finish: on 14 January 2027.',date('on the','unfinished','open_complement'),date('on 14 January 2027',resolution='exact_explicit',value='2027-01-14'),correction={'from':0,'to':1,'kind':'completion','effective':1}),
            variant('For the loan, on 14 January 2027... that is the complete date.',date('on 14 January 2027',resolution='exact_explicit',value='2027-01-14')),
            variant('For the loan, on the... I still have not finished choosing.',date('on the','unfinished','open_complement'),act='unfinished')]),
        root('T11','A fully uttered impossible calendar day differs from an open month complement.', 'What calendar entry are you proposing from that note?', [
            variant('The loan note lists 31 February 2027 as my payment day.',date('31 February 2027',resolution='impossible_calendar')),
            variant('The loan note lists the thirty-first of',date('the thirty-first of','unfinished','open_complement')),
            variant('The loan note lists 31 January 2027 as my payment day.',date('31 January 2027',resolution='exact_explicit',value='2027-01-31'))]),
        root('T12','Weekday/date conflict is complete, while missing month is unfinished.', 'Read the day and calendar date together from your payment note.', [
            variant('My payment note says Monday, 17 November 2026.',date('Monday, 17 November 2026',resolution='weekday_calendar_conflict')),
            variant('My payment note says Tuesday, 17 November 2026.',date('Tuesday, 17 November 2026',resolution='exact_explicit',value='2026-11-17')),
            variant('My payment note says Tuesday, the seventeenth of',date('Tuesday, the seventeenth of','unfinished','open_complement'))]),
        root('T13','Correction direction is semantic evidence and can leave an open current revision.', 'How are you revising the payment-date line?', [
            variant('The line was for the start of...; replace that with 6 January 2027.',date('the start of','unfinished','open_complement'),date('6 January 2027',resolution='exact_explicit',value='2027-01-06'),correction={'from':0,'to':1,'kind':'replacement','effective':1}),
            variant('The line was 6 January 2027; replace that with the start of...',date('6 January 2027',resolution='exact_explicit',value='2027-01-06'),date('the start of','unfinished','open_complement'),correction={'from':0,'to':1,'kind':'replacement','effective':1},act='unfinished'),
            variant('The line stays 6 January 2027; I am not replacing it.',date('6 January 2027',resolution='exact_explicit',value='2027-01-06'))]),
        root('T14','An actual prior unresolved complement can be completed only through a fixture-bound prior-event link.', 'Finish only the unresolved payment date you just began.', [
            variant('April.',date('April',resolution='linked_prior_expression'),context={'prior_fragment':'My payment day is the tenth of','linked':True}),
            variant('April.',date('April',resolution='unsupported_context'),context={'prior_fragment':'We were discussing a payment amount','linked':False}),
            variant('April or',date('April or','unfinished','open_alternative'),context={'prior_fragment':'My payment day is the tenth of','linked':True},act='unfinished')]),
        root('T15','Two endpoints of a payment window versus an open second endpoint.', 'What is the payment window in your travel diary?', [
            variant('My diary gives a window from 8 June to 11 June.',date('from 8 June to 11 June',resolution='date_range')),
            variant('My diary gives a window from 8 June to',date('from 8 June to','unfinished','open_range_endpoint')),
            variant('My diary gives a window sometime in June.',date('sometime in June',resolution='vague_period'))]),
        root('T16','A relational date uses an actually stated source anchor, with no implied exact calendar invention.', 'How does your payment day relate to your return trip?', [
            variant('Payment is on the day before my return trip.',date('the day before my return trip',resolution='unresolved_external_anchor')),
            variant('Payment is on the day before',date('the day before','unfinished','open_complement')),
            variant('Payment is two days before my return trip.',date('two days before my return trip',resolution='unresolved_external_anchor'))]),
        root('T17','Business-day ordinal is semantically complete without silently selecting a month.', 'Which business-day slot is marked in your payment planner?', [
            variant('The planner marks the fourth business day of July.',date('the fourth business day of July',resolution='underspecified_year')),
            variant('The planner marks the fourth business day of',date('the fourth business day of','unfinished','open_complement')),
            variant('The planner marks a business day in July.',date('a business day in July',resolution='vague_period'))]),
        root('T18','Month-end noun phrase and its incomplete genitive differ in delivered meaning.', 'Which month-end entry are you choosing for the loan?', [
            variant('I choose the final working day of August for the loan.',date('the final working day of August',resolution='underspecified_year')),
            variant('I choose the final working day of for the loan.',date('the final working day of','unfinished','open_complement')),
            variant('I choose the final working day for the loan.',date('the final working day','ambiguous','unresolved'),act='ambiguous')]),
        root('T19','Deictic date remains complete when a unique external anchor is absent.', 'What is the timing relation you mean for this payment?', [
            variant('My payment comes immediately after that day.',date('immediately after that day',resolution='unresolved_reference')),
            variant('My payment comes immediately after',date('immediately after','unfinished','open_complement')),
            variant('My payment comes on another date.',date('another date',resolution='vague_reference'))]),
        root('T20','Completed date survives an unfinished independent administrative question.', 'Which payment day are you selecting before your other question?', [
            variant('Select 24 November 2026 for the loan. Also, could the branch...',date('24 November 2026',resolution='exact_explicit',value='2026-11-24'),secondary=('information_question',)),
            variant('Select the twenty-fourth of for the loan. Also, could the branch explain its hours?',date('the twenty-fourth of','unfinished','open_complement'),secondary=('information_question',),act='unfinished'),
            variant('Select 24 November 2026 for the loan. Also, could the branch explain its hours?',date('24 November 2026',resolution='exact_explicit',value='2026-11-24'),secondary=('information_question',))]),
        root('T21','Numeric locale uncertainty is resolution ambiguity rather than expression incompletion.', 'What date is printed in the numeric payment box?', [
            variant('The payment box contains 04/06.',date('04/06',resolution='numeric_locale_ambiguous'),act='reported',primary='other'),
            variant('The payment box contains 04/.',date('04/','unfinished','open_numeric_month'),act='reported',primary='other'),
            variant('The payment box contains 4 June 2027.',date('4 June 2027',resolution='exact_explicit',value='2027-06-04'),act='reported',primary='other')]),
        root('T22','Explicitly started year cannot be filled from a yearless alternative or fixture clock.', 'What is the date on your long-range loan note?', [
            variant('The long-range note says June seventh, twenty...',date('June seventh, twenty','unfinished','open_year'),act='reported',primary='other'),
            variant('The long-range note says June seventh.',date('June seventh',resolution='underspecified_year'),act='reported',primary='other'),
            variant('The long-range note says June seventh, twenty twenty-eight.',date('June seventh, twenty twenty-eight',resolution='exact_explicit',value='2028-06-07'),act='reported',primary='other')]),
        root('T23','A completed choice has unresolved selection, whereas the alternative complement is still open.', 'What alternatives are in your payment-date shortlist?', [
            variant('My shortlist is either 10 September or 12 September.',date('either 10 September or 12 September',resolution='unresolved_choice'),act='uncommitted'),
            variant('My shortlist is either 10 September or the',date('either 10 September or the','unfinished','open_alternative'),act='unfinished'),
            variant('My shortlist is 10 September...',date('10 September','ambiguous','underspecified_year'),act='ambiguous')]),
        root('T24','Evening date complement is unfinished with no ellipsis at all.', 'Which dated evening are you putting in the repayment diary?', [
            variant('The diary sets repayment for the evening of',date('the evening of','unfinished','open_complement')),
            variant('The diary sets repayment for the evening of 21 December 2026.',date('the evening of 21 December 2026',resolution='exact_explicit',value='2026-12-21')),
            variant('The diary sets repayment for some evening next week.',date('some evening next week',resolution='vague_period'))])
    ]


def date_dev_roots():
    # Separately conceived carrier/episode inventory, never a TRAIN stem with
    # amounts, dates, products, names, or punctuation merely substituted.
    return [
        root('D01','A countdown tied to an unnamed milestone; no TRAIN relational phrase is reused.', 'How is the countdown in your repayment chart defined?', [
            variant('Zero in my repayment countdown is thirteen days from the inspection.',date('thirteen days from the inspection',resolution='unresolved_external_anchor')),
            variant('Zero in my repayment countdown is thirteen days from',date('thirteen days from','unfinished','open_complement')),
            variant('Zero in my repayment countdown is 2 February 2027.',date('2 February 2027',resolution='exact_explicit',value='2027-02-02'))]),
        root('D02','Customer defines a deadline through a duration following a move-in event.', 'How long after moving in is your repayment deadline?', [
            variant('Repayment falls within five days following the move-in.',date('within five days following the move-in',resolution='unresolved_external_anchor')),
            variant('Repayment falls within five days following',date('within five days following','unfinished','open_complement')),
            variant('Repayment falls within five days.',date('within five days',resolution='vague_period'))]),
        root('D03','Event-closing noun phrase provides a complete but externally unresolved day.', 'What event in your poster fixes the loan payment day?', [
            variant('The festival’s closing day fixes my loan payment.',date('The festival’s closing day',resolution='unresolved_external_anchor')),
            variant('The festival’s closing fixes my loan payment.',date('The festival’s closing','ambiguous','unresolved'),act='ambiguous'),
            variant('The closing day, 15 August 2027, fixes my loan payment.',date('15 August 2027',resolution='exact_explicit',value='2027-08-15'))]),
        root('D04','Possessive anaphor points to an independently spoken dated appointment, not a payment offer.', 'Which day of the appointment record do you wish to reuse?', [
            variant('Its scheduled day will also be my repayment day.',date('Its scheduled day',resolution='unresolved_reference')),
            variant('Its scheduled day of will also be my repayment day.',date('Its scheduled day of','unfinished','open_complement')),
            variant('A different scheduled day will be my repayment day.',date('A different scheduled day',resolution='vague_reference'))]),
        root('D05','Reported rejected due-date text from a printed schedule uses a fresh subordinate construction.', 'Which due-date text did you cross out in the printed schedule?', [
            variant('What I crossed out was “due before 19 March 2027”, without promising that date.',date('before 19 March 2027',resolution='date_bound',predicate='quoted_negated',act='reported'),primary='other',act='reported',predicate='quoted_negated'),
            variant('What I crossed out was “due before the”, without promising any date.',date('before the','unfinished','open_complement',predicate='quoted_negated',act='reported'),primary='other',act='reported',predicate='quoted_negated'),
            variant('What I crossed out was “due during spring”, without promising a day.',date('during spring',resolution='vague_period',predicate='quoted_negated',act='reported'),primary='other',act='reported',predicate='quoted_negated')]),
        root('D06','Two pages assign independent payment dates; a correction opens the second page only.', 'What dates belong on the first and second repayment pages?', [
            variant('Page one keeps 23 July 2027. Page two now reads the weekend beginning',date('23 July 2027',resolution='exact_explicit',value='2027-07-23',target=0),date('the weekend beginning','unfinished','open_complement',target=1)),
            variant('Page one keeps 23 July 2027. Page two now reads the weekend beginning 24 July 2027.',date('23 July 2027',resolution='exact_explicit',value='2027-07-23',target=0),date('the weekend beginning 24 July 2027',resolution='date_range',target=1)),
            variant('Page one is undated. Page two now reads the weekend beginning 24 July 2027.',date('the weekend beginning 24 July 2027',resolution='date_range',target=1))],products=('car_loan','credit_card')),
        root('D07','Sunday is fixed independently of an uncompleted clock-reading choice.', 'What have you fixed in the callback booking, and what remains open?', [
            variant('Sunday is fixed for the callback; the clock reading is still “half past”.',date('Sunday',resolution='relative_day'),time='unfinished',primary='callback_proposal'),
            variant('Sunday is fixed for the callback; the clock reading is 11:30.',date('Sunday',resolution='relative_day'),time='complete',primary='callback_proposal'),
            variant('The Sunday after is fixed for the callback; the clock reading is 11:30.',date('The Sunday after','unfinished','open_complement'),time='complete',primary='callback_proposal')],role='callback',phase='callback'),
        root('D08','An eclipse period is complete vague timing, with a dangling possessive contrast.', 'Which period around the eclipse are you proposing for the loan?', [
            variant('I propose repayment during next month’s eclipse.',date('during next month’s eclipse',resolution='vague_period')),
            variant('I propose repayment during next month’s',date('during next month’s','unfinished','open_possessive')),
            variant('I propose repayment during the eclipse... I still need to choose a day.',date('during the eclipse',resolution='vague_period'),act='uncommitted')])
    ]


# Explicit conservative fresh-root unions: the source objects remain distinct,
# but matching documentary carriers do not buy extra independent support.
NEW_UNIONS = (
    ('T03', 'T08', 'Quoted document ordinal-date versus open month complement shares a documentary carrier.'),
    ('T11', 'T12', 'Payment-note calendar-error contrasts share a documentary date carrier; invalidity types remain separate annotations.'),
)


def canonical_overlay(design, old_rows, specs):
    mapping = dict(design['v3_lineage_review_contract']['canonical_map'])
    parent = {g: g for g in set(mapping) | set(mapping.values())}
    def find(g):
        parent.setdefault(g, g)
        if parent[g] != g: parent[g] = find(parent[g])
        return parent[g]
    def join(a, b):
        ra, rb = find(a), find(b)
        parent[max(ra, rb)] = min(ra, rb)
    for a, b in mapping.items(): join(a, b)
    by_id = {r['example_id']: r for r in old_rows}
    edges = []
    for spec in specs:
        g = gid(spec['key'])
        find(g)
        for ancestor in spec['existing_ancestors']:
            ancestor_group = by_id[ancestor]['lineage_group_id']
            join(g, ancestor_group)
            edges.append(dict(a=g,b=ancestor_group,ancestor_example_id=ancestor,
                              reason=spec['overlap_reason']))
    for a, b, reason in NEW_UNIONS:
        join(gid(a), gid(b))
        edges.append(dict(a=gid(a),b=gid(b),reason=reason))
    return {g:find(g) for g in sorted(parent)}, edges


def boundary(text, surface, turn_id, occurrence=0):
    starts = [m.start() for m in re.finditer(re.escape(surface), text)]
    if not surface or occurrence >= len(starts):
        raise ValueError('Missing literal boundary: ' + repr(surface))
    start = starts[occurrence]
    return dict(turn_id=turn_id, start=start, end=start+len(surface), surface=surface,
                offset_unit='python_unicode_codepoints')


def make_record(spec, index, split, overlay, policy_hash, api_hash, source_hash):
    v = spec['variants'][index]
    g = gid(spec['key'])
    eid = eid_for(spec['key'],index)
    call_id, turn_id = eid + ':call', eid + ':user'
    products = [dict(index=i, product_id=g+':product:'+str(i),
                     type=p, label=p.replace('_',' '))
                for i,p in enumerate(spec['products'])]
    pending = []
    for target in products:
        i = target['index']
        pending.append(dict(target_index=i,
            components={name:dict(value=None, status='unfinished',
                revision=g+':target:'+str(i)+':'+name+':r1', evidence_refs=[])
                for name in ('amount','date')},
            unresolved_components=['amount','date']))
    events = []
    context = v['context']
    if spec['key'] == 'P11':
        events.append(dict(turn_id=eid+':earlier-proposal', role='user',
                           text='I am putting forward a loan payment proposal.', ordinal=1))
    if 'prior_fragment' in context:
        prior_id = eid + ':prior-fragment'
        events.append(dict(turn_id=prior_id,role='user',text=context['prior_fragment'],ordinal=1))
        if context.get('linked'):
            pending[0]['components']['date']['evidence_refs'] = [prior_id]
    offers = []
    for slot, value in enumerate(context.get('offers', [])):
        event_id = eid+':spoken-offer:'+str(slot)
        offers.append(dict(offer_id=eid+':offer:'+str(slot), semantic_role='offer',
                           source_rule_ids=['A23'], spoken_turn_id=event_id,
                           state_revision=2, superseded=False, target_indices=[0],
                           terms=[dict(target_index=0,date=value)]))
        events.append(dict(turn_id=event_id,role='assistant',
                           text='One loan date I can mention is '+value+'.',ordinal=slot+2))
    q_id = eid + ':question'
    events.append(dict(turn_id=q_id,role='assistant',text=spec['question'],ordinal=5))
    events.append(dict(turn_id=turn_id,role='user',text=v['text'],ordinal=6))
    snapshot = dict(schema_version='semantic_input.v1',call_local_id=call_id,
                    turn_id=turn_id,state_revision=3,policy_hash=policy_hash,
                    api_hash=api_hash,utterance=dict(text=v['text'],source='authored_fixture',
                    source_turn_id=turn_id,complete_transport=True,
                    offset_unit='python_unicode_codepoints'),phase=spec['phase'],
                    question=dict(question_id=eid+':q',role=spec['role'],
                        spoken_turn_id=q_id,target_indices=[t['index'] for t in products],
                        text=spec['question']),targets=products,pending=pending,
                    spoken_offers=offers,active_readback=None)
    candidates = []
    for j, candidate in enumerate(v['dates']):
        c = copy.deepcopy(candidate)
        surface, occurrence, clause = c.pop('surface'), c.pop('occurrence'), c.pop('clause')
        exact = boundary(v['text'],surface,turn_id,occurrence)
        c['candidate_id'] = eid+':oracle-date:'+str(j)
        c['source_boundary'] = exact
        c['clause_boundary'] = boundary(v['text'],clause or v['text'],turn_id)
        c['component'] = 'date'
        c['annotation_origin'] = 'weak_source_author_not_detector'
        slot = c['resolution'].pop('source_offer_slot')
        c['resolution']['source_offer_id'] = offers[slot]['offer_id'] if slot is not None else None
        c['binary_training_mask'] = False
        candidates.append(c)
    prior_link = None
    if context.get('linked'):
        prior_link = dict(source_turn_id=eid+':prior-fragment',
                          source_boundary=boundary(context['prior_fragment'],context['prior_fragment'],eid+':prior-fragment'),
                          target_index=0,component='date',
                          component_revision=pending[0]['components']['date']['revision'],
                          fixture_scope='synthetic_prior_event_link_only')
    origin = dict(scene=spec['scene'],question=spec['question'],role=spec['role'],
                  phase=spec['phase'],products=spec['products'],variant=v,
                  source_events=events)
    fixture = dict(scope='bounded_synthetic_only',runtime_authenticity='not_established',
                   current_speaker_role='user',person_scope='intended_person',
                   fixture_now='2026-11-16T09:20',source_events=events,
                   linked_continuation=prior_link)
    oracle = dict(schema_version='semantic_source_annotations.v3',
                  primary_intent=v['primary'],secondary_intents=v['secondary'],
                  primary_source_boundary=boundary(v['text'],v['text'],turn_id),
                  act_commitment=v['act_commitment'],predicate_scope=v['predicate_scope'],
                  time_completion=v['time_completion'],date_candidates=candidates,
                  correction_relation=v['correction'],
                  status='single_author_weak_proposal',independent_reviewer_count=0,
                  gold=False,training_admitted=False)
    return dict(example_id=eid,lineage_group_id=g,canonical_group_id=overlay[g],
                root_id=opaque('R',spec['key']),split=split,input=snapshot,
                input_snapshot_sha256=sha(encoded(snapshot)),
                source=dict(kind='fresh_authored_fictional',fictional=True,
                    author=AUTHOR,generator_model_version='inherited-workhorse fallback; exact version unavailable',
                    generation_prompt_sha256=sha(PROMPT.encode('utf-8')),
                    source_path=str(SELF.relative_to(ROOT)).replace('\\','/'),
                    source_sha256=source_hash,
                    literal_inventory_locator=dict(admin_manifest='research/customer-benchmark/semantic-v3-collection/manifest.json',
                        entry_id=eid),
                    source_episode_id=opaque('S',spec['key']),
                    template_root=g,state_carrier_id=opaque('C',spec['key']),
                    shared_author=True,shared_policy_context=True,
                    augmentation_parent_ids=[] if index==0 else [eid_for(spec['key'],0)],
                    existing_ancestor_example_ids=spec['existing_ancestors'],
                    license='LicenseRef-User-Authorized-Synthetic-RD',
                    origin_content_sha256=sha(encoded(origin))),
                source_fixture=fixture,oracle_annotations=oracle)


def reviewer_row(record, overlay):
    # The ONLY reviewer-visible material: exact observed input and IDs/groups.
    return dict(example_id=record['example_id'],input=copy.deepcopy(record['input']),
                lineage_group_id=record['lineage_group_id'],
                canonical_group_id=overlay[record['lineage_group_id']])


def pack(rows, split):
    return dict(schema_version='semantic_collection.v3',split=split,
                allowed_use='synthetic weak exploratory TRAIN/dev; not gold/human/qualification; no training metric',
                records=rows)


def review_pack(rows):
    # No task-specific labels, reasons, author IDs, nomination, source role
    # claims, status, weak strata, examples of desired answers, or oracle spans.
    return dict(schema_version='input_only_canonical_review_packet.v3',
                selected_canonical_groups=sorted({r['canonical_group_id'] for r in rows}),
                records=sorted(rows,key=lambda r:sha(r['example_id'].encode('utf-8'))))


def summarize(rows):
    groups = {r['canonical_group_id'] for r in rows}
    labels = Counter(c['expression_completion'] for r in rows
                     for c in r['oracle_annotations']['date_candidates'])
    support = {label:len({r['canonical_group_id'] for r in rows if any(
                    c['expression_completion']==label for c in r['oracle_annotations']['date_candidates'])})
               for label in ('complete','unfinished','ambiguous')}
    return dict(rows=len(rows),authored_roots=len({r['root_id'] for r in rows}),
                declared_groups=len({r['lineage_group_id'] for r in rows}),
                conservative_canonical_groups=len(groups),date_candidate_counts=dict(labels),
                weak_date_class_canonical_support=support,
                weak_primary_row_counts=dict(Counter(r['oracle_annotations']['primary_intent'] for r in rows)),
                independently_reviewed_rows=0,independently_adjudicated_gold_rows=0,
                training_admitted=False)


def build(repack_neutral_ids=False):
    previous={n:(DEST/n).read_bytes() for n in FILES if (DEST/n).exists()}
    if previous and not repack_neutral_ids:
        raise FileExistsError('Collection already frozen; --build refuses replacement.')
    if repack_neutral_ids and set(previous)!=set(FILES):
        raise ValueError('Identity repack requires all six worker-owned files.')
    # Read all context once before author files are saved. The exact contract
    # sections and original union map are snapshotted in the admin manifest.
    blobs = {p:(ROOT/p).read_bytes() for p in SOURCE_PATHS}
    design = json.loads(blobs[DESIGN_PATH])
    old_train = json.loads(blobs[TRAIN_PATH])['records']
    old_dev = json.loads(blobs[DEV_PATH])['records']
    old_packet = json.loads(blobs[PACKET_PATH])
    frozen = json.loads(blobs[FROZEN_MANIFEST])
    for artifact in frozen['artifacts']:
        if artifact['path'] in blobs:
            assert sha(blobs[artifact['path']]) == artifact['sha256'], 'Frozen input mismatch'
    specs = primary_roots()+date_train_roots()+date_dev_roots()
    overlay, edges = canonical_overlay(design,old_train,specs)
    source_hash = sha(SELF.read_bytes())
    rows = [make_record(s,i,'development' if s['key'].startswith('D') else 'train',
                        overlay,sha(blobs[POLICY_PATH]),sha(blobs[API_PATH]),source_hash)
            for s in specs for i in range(len(s['variants']))]
    identity_repack=None
    if previous:
        # Explicit user steering authorized this local prereview packaging
        # change. Prove every old input is identical after opaque identity
        # rebinding; source text, context roles and state meanings stay frozen.
        old_rows=[r for n in FILES[:3] for r in json.loads(previous[n])['records']]
        new_by_id={r['example_id']:r for r in rows}
        bindings=[]
        for old in old_rows:
            key=old['root_id']
            index=old['source']['literal_inventory_locator']['variant_index']
            new=new_by_id[eid_for(key,index)]
            rebound=encoded(old['input']).decode('utf-8').replace(old['example_id'],new['example_id']).replace(old['lineage_group_id'],new['lineage_group_id'])
            assert json.loads(rebound)==new['input'],'Identity repack changed source meaning'
            bindings.append(dict(previous_example_id=old['example_id'],example_id=new['example_id'],
                previous_lineage_group_id=old['lineage_group_id'],lineage_group_id=new['lineage_group_id'],
                previous_input_snapshot_sha256=old['input_snapshot_sha256'],
                input_snapshot_sha256=new['input_snapshot_sha256']))
        identity_repack=dict(reason='Explicit user request for opaque class-neutral prereview identities; source content frozen.',
            input_identity_rebinding_only=True,raw_source_text_and_context_preserved=True,
            previous_artifacts=[dict(path=n,sha256=sha(b),bytes=len(b)) for n,b in previous.items()],
            example_bindings=bindings)
    primary_ids={eid_for(s['key'],i) for s in primary_roots() for i in range(len(s['variants']))}
    train_ids={eid_for(s['key'],i) for s in date_train_roots() for i in range(len(s['variants']))}
    primary = [r for r in rows if r['example_id'] in primary_ids]
    train = [r for r in rows if r['example_id'] in train_ids]
    dev = [r for r in rows if r['split']=='development']
    old_ids = {r['example_id'] for r in old_packet['records']}
    old_by_id = {r['example_id']:r for r in old_train}
    assert all(r['input']==old_by_id[r['example_id']]['input'] for r in old_packet['records'])
    selected = {overlay[r['lineage_group_id']] for r in old_packet['records']}
    selected.add(overlay[old_by_id['CSv2-E-0109']['lineage_group_id']])
    selected |= {r['canonical_group_id'] for r in primary}
    existing_closure = [r for r in old_train if overlay[r['lineage_group_id']] in selected]
    primary_review = review_pack([reviewer_row(r,overlay) for r in existing_closure+primary])
    date_review = review_pack([reviewer_row(r,overlay) for r in train])
    objects = {'primary-supplement-train.json':pack(primary,'train'),
               'date-train.json':pack(train,'train'),'date-dev.json':pack(dev,'development'),
               'label-free-primary-review-packet.json':primary_review,
               'label-free-date-review-packet.json':date_review}
    manifest = dict(schema_version='semantic_collection_admin_manifest.v3',
        status='synthetic single-author weak TRAIN/dev collection; review and detector alignment pending',
        created_utc=datetime.now(timezone.utc).isoformat(),author=AUTHOR,
        generator_model_version='inherited-workhorse fallback; exact version not available; no GPT-5.6 claim',
        prompt=PROMPT,prompt_sha256=sha(PROMPT.encode('utf-8')),
        license='LicenseRef-User-Authorized-Synthetic-RD',
        raw_customer_pii=False,raw_public_customer_text=False,network_used=False,
        source_policy='Immutable brief/API constrain source context; they do not define linguistic labels or bank outcomes.',
        contracts_snapshot={k:copy.deepcopy(design[k]) for k in
            ('v3_lineage_review_contract','date_completion_subset_experiment',
             'cpu_date_completion_pilot_v3','v3_shared_admissible_feature_contract')},
        exact_current_date_execution_contract_key='cpu_date_completion_pilot_v3',
        input_snapshot_schema=copy.deepcopy(frozen['schemas']['pack']['properties']['records']['items']['properties']['input']),
        source_pins=[dict(path=p,sha256=sha(b),bytes=len(b)) for p,b in blobs.items()]+
                    [dict(path=str(SELF.relative_to(ROOT)).replace('\\','/'),sha256=source_hash,bytes=SELF.stat().st_size)],
        lineage=dict(canonical_id_rule='Lexically minimum original ID in transitive union; preserve declared root IDs.',
            canonical_map=overlay,new_union_edges=edges,
            old_train_groups=sorted({r['lineage_group_id'] for r in old_train}),
            old_dev_groups=sorted({r['lineage_group_id'] for r in old_dev}),
            limitation='Shared author and policy; distinct scene IDs do not prove IID roots. Fresh documentary carrier collisions are conservatively united.',
            roots=[dict(root_id=opaque('R',s['key']),author_root_key=s['key'],lineage_group_id=gid(s['key']),
                        canonical_group_id=overlay[gid(s['key'])],scene=s['scene'],
                        existing_ancestors=s['existing_ancestors'],
                        source_episode_id=opaque('S',s['key']),
                        state_carrier_id=opaque('C',s['key'])) for s in specs]),
        literal_inventory={eid_for(s['key'],i):dict(author_root_key=s['key'],
            variant_index=i,source_function=('primary_roots' if s['key'].startswith('P') else 'date_train_roots' if s['key'].startswith('T') else 'date_dev_roots'),
            scene=s['scene'],author_rationale=v['rationale'] or s['scene'])
            for s in specs for i,v in enumerate(s['variants'])},
        identity_policy='Opaque class-neutral NEW example/group/root/episode/carrier IDs. Author key, root descriptions, rationale and nominations live only in this admin manifest. Earlier frozen source IDs are preserved.',
        identity_repack=identity_repack,
        counts=dict(primary=summarize(primary),date_train=summarize(train),date_dev=summarize(dev)),
        primary_authored_nomination=dict(payment_roots=['P%02d'%i for i in range(1,9)],
            nonpayment_roots=['P%02d'%i for i in range(9,13)],
            basis='Loose source-author hypothesis before any model or detector predictions; never reviewer-visible or readiness evidence.'),
        primary_packet_closure=dict(original_packet_rows=len(old_ids),
            original_packet_sha256=sha(blobs[PACKET_PATH]),
            original_source_train_sha256=sha(blobs[TRAIN_PATH]),
            existing_closure_rows=len(existing_closure),new_supplement_rows=len(primary),
            rows=len(primary_review['records']),canonical_groups=len(primary_review['selected_canonical_groups']),
            added_existing_example_ids=sorted({r['example_id'] for r in existing_closure}-old_ids),
            selected_canonical_groups=primary_review['selected_canonical_groups']),
        primary_new_ancestry_counts=dict(total_authored_root_carriers=12,
            carriers_with_existing_train_ancestry=2,new_canonical_groups_outside_existing_train=10,
            nominated_payment_carriers=8,nominated_payment_canonical_groups_outside_existing_train=6,
            meaning='Weak authorship only; not reviewed support or a passed primary gate.'),
        review_input_bindings={r['example_id']:dict(input_snapshot_sha256=sha(encoded(r['input'])),
            lineage_group_id=r['lineage_group_id'],canonical_group_id=overlay[r['lineage_group_id']],
            source_path=(TRAIN_PATH if r['example_id'] in old_by_id else 'research/customer-benchmark/semantic-v3-collection/'+('primary-supplement-train.json' if r['example_id'] in primary_ids else 'date-train.json')),
            source_ancestor_example_ids=(r['source'].get('existing_ancestor_example_ids',[]) if r['example_id'] not in old_by_id else r['source'].get('augmentation_parent_ids',[])))
            for r in existing_closure+primary+train},
        date_packet=dict(rows=len(date_review['records']),split='train',
                         canonical_groups=len(date_review['selected_canonical_groups']),dev_included=False),
        review_policy=dict(author_files_are_admin_only=True,packets_label_free=True,
            reviewers_required_per_row=2,reviewers_must_be_non_author=True,
            exposure_and_identity_verified_by_parent=True,conflict_adjudication_required=True,
            original_81_row_packet_unchanged=True),
        feature_policy=dict(new_row_admission='All NEW source fixtures are non-security, synthetic and contain no DOB/phone answer values.',
            old_review_rows_admission='NOT feature-admitted by this collection. Earlier packet contains security/identity fixtures; parent must apply the v3 source eligibility contract before any features/cache/upload.',
            allowed='input only with versioned v3 lexical/value abstraction and typed target relations; oracle annotations and source metadata never features.',
            forbidden=['oracle_annotations','labels','nomination','sampling_strata','rationale',
                'IDs','hashes','filenames','split','source_metadata','canonical_dates',
                'DOB','security_answers','opaque_revision_tokens','future_turns','bank_outcomes'],
            actual_detector_outputs_present=False,detector_alignment_pending=True,
            oracle_spans_are_not_detector_candidates=True,training_requires_actual_detector_alignment=True,
            dev_training_or_upload_admission=False),
        detector_regression_scope='Eight additional no-date/competing-kind roots in the design are not authored in this assigned 24+8 completion pilot; do not claim detector regression coverage.',
        readiness=dict(independent_reviews=0,adjudicated_gold_rows=0,primary_admitted=False,
                       date_admitted=False,reason='Weak authorship; review, adjudication and actual detector alignment pending.',
                       calibration=False,risk=False,qualification=False,human_gold=False,
                       training_metric=False,models_or_existing_labels_mutated=False),
        artifacts=[dict(path=str((DEST/n).relative_to(ROOT)).replace('\\','/'),
                        sha256=sha(encoded(obj)),bytes=len(encoded(obj))) for n,obj in objects.items()])
    objects['manifest.json'] = manifest
    DEST.mkdir(parents=True,exist_ok=True)
    for name,obj in objects.items():
        with (DEST/name).open('wb' if repack_neutral_ids else 'xb') as f: f.write(encoded(obj))
    return manifest


def collection():
    return {n:load(DEST/n) for n in FILES}


def value_free_probe(record):
    """Integrity-only view, NOT the eventual detector-fed trainer interface.

    Whole input, IDs, annotations, terms and fixtures cannot slip into this
    probe. Future training must use the parent's versioned feature builder and
    actual candidates; this simply checks that NEW non-security sources can
    supply a value-free lexical/context view without reading author outcomes.
    """
    inp = record['input']
    def lexical(text):
        text = re.sub(r'\b\d+(?:[/:.-]\d+)*\b','<value>',text)
        return text
    return dict(current_user=lexical(inp['utterance']['text']),
                question=lexical(inp['question']['text']),phase=inp['phase'],
                question_role=inp['question']['role'],
                pending_relations=[dict(is_question_target=p['target_index'] in inp['question']['target_indices'],
                    statuses={k:v['status'] for k,v in p['components'].items()},
                    unresolved_components=p['unresolved_components']) for p in inp['pending']],
                offer_presence=bool(inp['spoken_offers']))


class SemanticCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=collection()
        cls.manifest=cls.data['manifest.json']
        cls.rows=[r for n in FILES[:3] for r in cls.data[n]['records']]

    def test_counts_unique_ids_and_whole_root_variants(self):
        self.assertEqual(len(self.rows),132)
        self.assertEqual(len({r['example_id'] for r in self.rows}),len(self.rows))
        for name,roots,rows in [('primary-supplement-train.json',12,36),('date-train.json',24,72),('date-dev.json',8,24)]:
            records=self.data[name]['records']
            self.assertEqual(len(records),rows)
            self.assertEqual(len({r['root_id'] for r in records}),roots)
            self.assertEqual(set(Counter(r['root_id'] for r in records).values()),{3})

    def test_schema_bounded_inputs_finite_content_and_snapshot_hashes(self):
        import jsonschema
        schema=self.manifest['input_snapshot_schema']
        for r in self.rows:
            jsonschema.validate(r['input'],schema)
            self.assertEqual(r['input_snapshot_sha256'],sha(encoded(r['input'])))
            self.assertLessEqual(len(r['input']['utterance']['text']),4096)
            self.assertEqual(r['input']['targets'][0]['index'],0)
            self.assertNotIn('target_index',r['input']['targets'][0])
            for p in r['input']['pending']:
                self.assertIsInstance(p['components']['date'],dict)
        for n in FILES:
            self.assertLess((DEST/n).stat().st_size,2_000_000)
            load(DEST/n)  # Strict duplicate/nonfinite checks.

    def test_source_inventory_literal_alignment_and_hash_provenance(self):
        inventory={opaque('R',s['key']):s for s in primary_roots()+date_train_roots()+date_dev_roots()}
        for r in self.rows:
            source=r['source'];spec=inventory[r['root_id']]
            index=self.manifest['literal_inventory'][r['example_id']]['variant_index']
            self.assertEqual(r['input']['utterance']['text'],spec['variants'][index]['text'])
            self.assertEqual(r['input']['question']['text'],spec['question'])
            self.assertEqual(source['source_sha256'],sha(SELF.read_bytes()))
            self.assertEqual(source['generation_prompt_sha256'],sha(PROMPT.encode('utf-8')))
            origin=dict(scene=spec['scene'],question=spec['question'],role=spec['role'],
                phase=spec['phase'],products=spec['products'],variant=spec['variants'][index],
                source_events=r['source_fixture']['source_events'])
            self.assertEqual(source['origin_content_sha256'],sha(encoded(origin)))
            self.assertTrue(source['fictional'])
            self.assertEqual(r['source_fixture']['runtime_authenticity'],'not_established')
        for artifact in self.manifest['artifacts']:
            blob=(ROOT/artifact['path']).read_bytes()
            self.assertEqual(len(blob),artifact['bytes'])
            self.assertEqual(sha(blob),artifact['sha256'])

    def test_exact_unicode_candidate_and_clause_boundaries(self):
        saw_unicode=False
        for r in self.rows:
            text=r['input']['utterance']['text'];turn=r['input']['turn_id']
            saw_unicode |= any(ord(ch)>127 for ch in text)
            oracle=r['oracle_annotations']
            for candidate in oracle['date_candidates']:
                for field in ('source_boundary','clause_boundary'):
                    b=candidate[field]
                    self.assertEqual(b['turn_id'],turn)
                    self.assertEqual(b['offset_unit'],'python_unicode_codepoints')
                    self.assertTrue(0<=b['start']<b['end']<=len(text))
                    self.assertEqual(text[b['start']:b['end']],b['surface'])
                b,c=candidate['source_boundary'],candidate['clause_boundary']
                self.assertTrue(c['start']<=b['start']<b['end']<=c['end'])
                self.assertLessEqual(b['end']-b['start'],512)
            self.assertEqual(oracle['primary_source_boundary']['surface'],text)
        self.assertTrue(saw_unicode)

    def test_transitive_canonical_closure_and_exact_legacy_input(self):
        manifest=self.manifest;overlay=manifest['lineage']['canonical_map']
        old=load(ROOT/TRAIN_PATH)['records']
        packet=self.data['label-free-primary-review-packet.json']
        selected=set(packet['selected_canonical_groups'])
        primary=self.data['primary-supplement-train.json']['records']
        expected={r['example_id'] for r in old+primary if overlay[r['lineage_group_id']] in selected}
        actual={r['example_id'] for r in packet['records']}
        self.assertEqual(actual,expected)
        self.assertIn('CSv2-E-0073',actual)
        self.assertIn('CSv2-E-0109',actual)
        original=load(ROOT/PACKET_PATH)
        self.assertEqual(len(original['records']),81)
        self.assertTrue({r['example_id'] for r in original['records']}<=actual)
        inputs={r['example_id']:r['input'] for r in old+primary}
        for row in packet['records']:
            self.assertEqual(row['input'],inputs[row['example_id']])
            self.assertEqual(row['canonical_group_id'],overlay[row['lineage_group_id']])
        for a,b,_ in NEW_UNIONS:
            self.assertEqual(overlay[gid(a)],overlay[gid(b)])
        self.assertEqual(overlay[gid('P06')],overlay['CSv2-G-74bae451056bdbc2'])
        for row in packet['records']:
            binding=manifest['review_input_bindings'][row['example_id']]
            self.assertEqual(binding['input_snapshot_sha256'],sha(encoded(row['input'])))
            self.assertEqual(binding['canonical_group_id'],row['canonical_group_id'])

    def test_train_dev_root_template_episode_state_and_ancestor_disjoint(self):
        train=[r for r in self.rows if r['split']=='train']
        dev=[r for r in self.rows if r['split']=='development']
        for field in ('root_id','lineage_group_id','canonical_group_id','example_id'):
            self.assertFalse({r[field] for r in train}&{r[field] for r in dev})
        for field in ('source_episode_id','template_root','state_carrier_id','origin_content_sha256'):
            self.assertFalse({r['source'][field] for r in train}&{r['source'][field] for r in dev})
        for field in ('question',):
            self.assertFalse({r['input'][field]['text'] for r in train}&{r['input'][field]['text'] for r in dev})
        self.assertFalse({r['input']['utterance']['text'] for r in train}&{r['input']['utterance']['text'] for r in dev})
        old_dev=load(ROOT/DEV_PATH)['records']
        old_dev_groups={r['lineage_group_id'] for r in old_dev}
        self.assertFalse({r['canonical_group_id'] for r in train}&old_dev_groups)
        self.assertTrue(all(not r['source']['existing_ancestor_example_ids'] for r in dev))
        for name in ('label-free-primary-review-packet.json','label-free-date-review-packet.json'):
            self.assertFalse({r['example_id'] for r in self.data[name]['records']}&{r['example_id'] for r in dev+old_dev})

    def test_review_packets_exact_input_ids_groups_only_and_date_train_closure(self):
        for name in ('label-free-primary-review-packet.json','label-free-date-review-packet.json'):
            p=self.data[name]
            self.assertEqual(set(p),{'schema_version','selected_canonical_groups','records'})
            self.assertEqual(len(p['records']),len({r['example_id'] for r in p['records']}))
            for r in p['records']:
                self.assertEqual(set(r),{'example_id','input','lineage_group_id','canonical_group_id'})
            self.assertEqual(set(p['selected_canonical_groups']),{r['canonical_group_id'] for r in p['records']})
        train=self.data['date-train.json']['records']
        expected={r['example_id']:r['input'] for r in train}
        actual={r['example_id']:r['input'] for r in self.data['label-free-date-review-packet.json']['records']}
        self.assertEqual(expected,actual)

    def test_new_identity_and_metadata_are_opaque_class_neutral(self):
        for r in self.rows:
            for name,kind in [('example_id','E'),('lineage_group_id','G'),('root_id','R')]:
                self.assertRegex(r[name],r'^SV3-'+kind+r'-[0-9a-f]{20}$')
            metadata=encoded(r['source']).decode('utf-8')
            for forbidden in ('PAYpositive','NEG','complete','incomplete','author_rationale','scene','root_nomination','sampling_strata','author_root_key','primary_roots','date_train_roots','date_dev_roots'):
                self.assertNotIn(forbidden,metadata)
            self.assertNotIn('author_rationale',r['oracle_annotations'])
        for name in ('label-free-primary-review-packet.json','label-free-date-review-packet.json'):
            for r in self.data[name]['records']:
                if r['example_id'].startswith('SV3-'):
                    self.assertRegex(r['example_id'],r'^SV3-E-[0-9a-f]{20}$')
                    self.assertRegex(r['lineage_group_id'],r'^SV3-G-[0-9a-f]{20}$')

    def test_date_semantics_orthogonal_axes_not_ellipsis_or_validity_labels(self):
        by_id={r['example_id']:r for r in self.rows}
        def row_for(key):
            source_key,idx=key.split('-')
            return by_id[eid_for(source_key,int(idx)-1)]
        def candidates(key):return row_for(key)['oracle_annotations']['date_candidates']
        for key,status in [('T05-1','unique_spoken_offer'),('T05-2','no_offer_referent'),('T05-3','multiple_offer_referents')]:
            c=candidates(key)[0]
            self.assertEqual(c['expression_completion'],'complete')
            self.assertEqual(c['resolution']['status'],status)
        for key,status in [('T11-1','impossible_calendar'),('T12-1','weekday_calendar_conflict')]:
            c=candidates(key)[0]
            self.assertEqual(c['expression_completion'],'complete')
            self.assertEqual(c['resolution']['status'],status)
            self.assertIsNone(c['resolution']['canonical_date'])
        for key in ('T07-1','T08-1','T09-1','T04-1','T20-1','D07-1'):
            self.assertEqual(candidates(key)[0]['expression_completion'],'complete')
        self.assertEqual(candidates('T10-2')[0]['expression_completion'],'complete')
        self.assertEqual(candidates('T23-3')[0]['expression_completion'],'ambiguous')
        self.assertEqual(candidates('T24-1')[0]['expression_completion'],'unfinished')
        for key,effective,label in [('T13-1',1,'complete'),('T13-2',1,'unfinished')]:
            r=row_for(key);o=r['oracle_annotations']
            self.assertEqual(o['correction_relation']['effective'],effective)
            self.assertEqual(o['date_candidates'][effective]['expression_completion'],label)
        self.assertEqual(candidates('T06-1')[0]['target_index'],0)
        self.assertEqual(candidates('T06-1')[1]['target_index'],1)
        for r in self.rows:
            for c in r['oracle_annotations']['date_candidates']:
                self.assertIn(c['expression_completion'],('complete','unfinished','ambiguous'))
                self.assertFalse(c['binary_training_mask'])
                if c['resolution']['status'] not in ('exact_explicit','unique_spoken_offer'):
                    self.assertIsNone(c['resolution']['canonical_date'])

    def test_linked_continuation_and_unique_offer_source_binding(self):
        by_id={r['example_id']:r for r in self.rows}
        linked=by_id[eid_for('T14',0)];unlinked=by_id[eid_for('T14',1)]
        self.assertEqual(linked['input']['utterance']['text'],unlinked['input']['utterance']['text'])
        link=linked['source_fixture']['linked_continuation']
        events={e['turn_id']:e for e in linked['source_fixture']['source_events']}
        self.assertEqual(events[link['source_turn_id']]['text'],link['source_boundary']['surface'])
        self.assertIn(link['source_turn_id'],linked['input']['pending'][0]['components']['date']['evidence_refs'])
        self.assertEqual(link['component_revision'],linked['input']['pending'][0]['components']['date']['revision'])
        self.assertIsNone(unlinked['source_fixture']['linked_continuation'])
        r=by_id[eid_for('T05',0)];c=r['oracle_annotations']['date_candidates'][0]
        offer=r['input']['spoken_offers'][0]
        self.assertEqual(c['resolution']['source_offer_id'],offer['offer_id'])
        self.assertEqual(c['resolution']['canonical_date'],offer['terms'][0]['date'])
        self.assertIn(offer['spoken_turn_id'],{e['turn_id'] for e in r['source_fixture']['source_events']})

    def test_primary_nomination_is_weak_and_nonpayment_can_contain_payment(self):
        primary=self.data['primary-supplement-train.json']['records']
        for r in primary:
            o=r['oracle_annotations']
            key=self.manifest['literal_inventory'][r['example_id']]['author_root_key']
            expected='payment_proposal' if int(key[1:])<=8 else ('human_request' if key=='P09' else 'correction' if key=='P11' else 'information_question')
            self.assertEqual(o['primary_intent'],expected)
            self.assertEqual(o['independent_reviewer_count'],0)
            self.assertFalse(o['training_admitted'])
            self.assertFalse(o['gold'])
            if key=='P09':self.assertIn('payment_proposal',o['secondary_intents'])
            if key=='P10':self.assertEqual(o['predicate_scope'],'hypothetical')
            if key=='P11':self.assertEqual(o['act_commitment'],'withdrawn')
            if key=='P12':self.assertEqual(o['predicate_scope'],'negated')

    def test_new_features_secret_absence_outcome_exclusion_and_id_invariance(self):
        forbidden_values={'0047','0048','1984','zero zero','nineteen eighty-four'}
        for r in self.rows:
            view=value_free_probe(r)
            serialized=json.dumps(view,ensure_ascii=False).lower()
            for token in forbidden_values:self.assertNotIn(token,serialized)
            for term in ('date of birth','birthday','phone number','security answer','last four'):
                self.assertNotIn(term,serialized)
            for field in ('oracle_annotations','canonical_date','product_id','revision','sha256','example_id','split'):
                self.assertNotIn(field,serialized)
            changed=copy.deepcopy(r)
            changed['example_id']='irrelevant'
            changed['oracle_annotations']={'primary_intent':'WRONG','date_candidates':[]}
            changed['input']['turn_id']='new-event-id'
            changed['input']['call_local_id']='new-call-id'
            for p in changed['input']['pending']:
                for c in p['components'].values():c['revision']='renamed-token'
            self.assertEqual(view,value_free_probe(changed))
        self.assertFalse(self.manifest['feature_policy']['actual_detector_outputs_present'])
        self.assertFalse(self.manifest['feature_policy']['dev_training_or_upload_admission'])

    def test_frozen_sources_and_original_packet_remain_byte_identical(self):
        # Design is co-owned by the parent and may acquire later sections.
        # Its frozen contract snapshot stays bound to this collection's pin.
        for source in self.manifest['source_pins']:
            if source['path']==DESIGN_PATH:continue
            self.assertEqual(sha((ROOT/source['path']).read_bytes()),source['sha256'])
        self.assertEqual(self.manifest['exact_current_date_execution_contract_key'],'cpu_date_completion_pilot_v3')
        self.assertFalse(self.manifest['readiness']['primary_admitted'])
        self.assertFalse(self.manifest['readiness']['date_admitted'])


def run_tests():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(SemanticCollectionTests)
    return unittest.TextTestRunner(verbosity=2).run(suite)


def report(test_result=None, customer_result=None):
    d=collection();m=d['manifest.json']
    artifacts=[dict(path=str((DEST/n).relative_to(ROOT)).replace('\\','/'),
                    sha256=sha((DEST/n).read_bytes()),bytes=(DEST/n).stat().st_size) for n in FILES]
    result=dict(status='synthetic weak TRAIN/dev authored and locally validated; not gold/human/qualification or training metric',
        author=AUTHOR,completed_utc=datetime.now(timezone.utc).isoformat(),
        exact_date_contract_key=m['exact_current_date_execution_contract_key'],
        counts=m['counts'],primary_packet=m['primary_packet_closure'],date_packet=m['date_packet'],
        primary_new_ancestry_counts=m['primary_new_ancestry_counts'],
        artifacts=artifacts,meaningful_checks=['unique IDs and root closure','strict finite bounded JSON',
            'frozen semantic_input.v1 schema','literal source inventory and input snapshot hashes',
            'exact Unicode candidate/clause source boundaries','transitive canonical closure including 0073 and whole 0109 group',
            'TRAIN/DEV canonical/root/template/episode/state ancestry separation',
            'reviewer exact inputs with IDs/groups only','separate expression, resolution, act and predicate labels',
            'linked continuation and actual synthetic spoken-offer binding','feature secret absence and ID/oracle invariance',
            'earlier packet and frozen source byte hashes'],
        collection_tests=(dict(run=test_result.testsRun,failures=len(test_result.failures),
                              errors=len(test_result.errors),skipped=len(test_result.skipped)) if test_result else None),
        customer_suite=customer_result,
        limitations=['Zero independent reviewers/adjudicated gold; all masks closed.',
            'Oracle candidate boundaries are source annotations, not actual detector output; detector alignment remains required.',
            'All origins share this author and the brief/API. IDs do not establish IID support.',
            '24 fresh DATE source roots collapse to 22 conservative canonical groups after two carrier unions.',
            'New primary supplement uses conservative older TRAIN ancestry for two carriers.',
            'Existing primary packet includes security fixtures and is not feature-admitted by this collection.',
            'No model fit, training upload, platform/cloud action, qualification metric, or parent queue use.',
            m['detector_regression_scope']])
    REPORT.with_suffix('.json').write_bytes(encoded(result))
    lines=[result['status'], '', 'Counts:']
    for k,v in result['counts'].items():
        lines.append(f"{k}: {v['rows']} rows / {v['authored_roots']} authored roots / {v['conservative_canonical_groups']} canonical groups.")
    lines += [f"Primary review packet: {m['primary_packet_closure']['rows']} rows / {m['primary_packet_closure']['canonical_groups']} canonical groups; adds existing IDs {m['primary_packet_closure']['added_existing_example_ids']}.",
              f"DATE review packet: {m['date_packet']['rows']} TRAIN-only rows / {m['date_packet']['canonical_groups']} canonical groups.",
              'Collection tests: '+json.dumps(result['collection_tests']),
              'Customer suite: '+json.dumps(customer_result), '', 'SHA-256:']
    lines += [a['path']+' '+a['sha256'] for a in artifacts]
    lines += ['', 'Checks:']+result['meaningful_checks']+['','Limitations:']+result['limitations']
    REPORT.with_suffix('.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(counts=result['counts'],primary_packet_rows=m['primary_packet_closure']['rows'],
                         collection_tests=result['collection_tests'],artifacts=artifacts),ensure_ascii=False,indent=2))


if __name__=='__main__':
    if '--build' in sys.argv:build(repack_neutral_ids='--repack-neutral-ids' in sys.argv)
    result=run_tests()
    if '--report' in sys.argv:report(result)
    raise SystemExit(0 if result.wasSuccessful() else 1)
