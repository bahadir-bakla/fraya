"""New fictional authored sources. Families, not slot variants, are embargo units.

Label vectors describe observable current semantics only. These are synthetic
engineering targets, with no independent human adjudication or IID assertion.
"""

LABELS = ['proposal', 'dispute', 'correction', 'current_affirm', 'current_withdraw', 'uncertain', 'reported_third_party']
AUTHOR_LICENSE = 'LicenseRef-User-Authorized-Synthetic-RD'

# Each record is a complete scenario recipe; all phrasing and slot descendants
# stay in its root. Placeholder values are entirely fictional.
TRAIN = [
 ('pay-wages', 'What payment can you personally make toward the balance?', ['I will pay {amount} on {date}.', 'My plan is to send {amount} after payday on {date}.', 'I can commit to a payment of {amount} on {date}.'], ['proposal']),
 ('split-principal-fee', 'The statement separates the principal from the late fee. What do you want to do?', ['I will pay the principal on {date}, but that late fee is wrong.', 'I dispute the fee; I will still send {amount} toward the principal on {date}.', 'That fee was charged in error. I can pay {amount} for the undisputed balance.'], ['proposal','dispute']),
 ('replace-own-amount', 'You proposed paying {old_amount} on {date}. Is that still your plan?', ['I meant {amount}, not {old_amount}; I will pay the smaller amount on {date}.', 'Change my proposed amount to {amount}. I will send it on {date}.', 'My earlier figure was a mistake. I am offering {amount} instead.'], ['proposal','correction']),
 ('replace-own-date', 'Earlier you offered a payment on {old_date}. What date did you intend?', ['I meant {date}; I will pay then instead of {old_date}.', 'Replace {old_date} with {date} for my payment plan.', 'I got the day wrong. My payment will be on {date}.'], ['proposal','correction']),
 ('contingent-income', 'When can you pay the outstanding balance?', ['If my wages arrive on {date}, I might pay {amount}.', 'I may be able to pay {amount}, depending on whether the transfer clears.', 'Perhaps I can pay on {date}; I cannot promise yet.'], ['proposal','uncertain']),
 ('unfinished-pay-date', 'When would you make your payment?', ['I will pay {amount} on the...', 'My payment would be on the first Monday after...', 'I can send it between {date} and...'], ['proposal','uncertain']),
 ('unfinished-correction', 'You offered to pay on {old_date}. Is that the correct date?', ['No, I meant the day after...', 'Change that to the second Friday of...', 'I meant between {date} and...'], ['correction','uncertain']),
 ('missing-transfer', 'The ledger shows that your transfer reached the account. Is that accurate?', ['That is wrong; the transfer never reached my account.', 'I dispute that posted transfer. It was returned.', 'The ledger claim is incorrect; I did not receive the money.'], ['dispute']),
 ('charge-ownership', 'Do you recognize this card purchase?', ['I never made that purchase; it is not mine.', 'That charge belongs to someone else, and I dispute it.', 'I contest responsibility for this purchase.'], ['dispute']),
 ('duplicate-debit', 'What looks wrong on your statement?', ['The same debit appears twice. I dispute the duplicate.', 'I was charged twice for one purchase; the second debit is wrong.', 'Only one purchase happened. That extra debit is incorrect.'], ['dispute']),
 ('paid-already', 'The balance is still marked unpaid.', ['I paid that bill already; the unpaid status is wrong.', 'I dispute the outstanding balance because my payment already cleared.', 'The statement is incorrect. This bill was settled.'], ['dispute']),
 ('wrong-account-repair', 'You said the issue was with your savings account.', ['I meant the checking account, not the savings account.', 'Correct the account type to checking.', 'You misunderstood me: the issue is checking, not savings.'], ['correction']),
 ('wrong-channel-repair', 'You asked for a telephone callback.', ['I meant an email reply, not a call.', 'Please correct that: I asked for written contact.', 'Change the contact channel to email; I misspoke.'], ['correction']),
 ('first-decline', 'May I debit {amount} from your account? No permission has been given yet.', ['No, I do not give permission.', 'I decline that request.', 'You do not have my approval to debit it.'], []),
 ('revoke-existing-debit', 'You previously permitted a debit of {amount}. Should that permission remain active?', ['Cancel my earlier permission to debit it.', 'I revoke the authorization I gave before.', 'Stop that debit; I withdraw my earlier approval.'], ['current_withdraw']),
 ('pause-existing-plan', 'You previously agreed to the payment arrangement.', ['Put my earlier arrangement on hold.', 'Pause the plan I accepted until I contact you again.', 'Suspend my previously agreed payment schedule.'], ['current_withdraw']),
 ('revoke-contact', 'You previously allowed us to telephone you about the balance.', ['I withdraw that permission to call me.', 'Stop using my earlier approval for telephone contact.', 'My previous consent to calls is revoked.'], ['current_withdraw']),
 ('negated-stop', 'Should I cancel your previously agreed payment?', ['I am not asking you to stop it.', 'Do not cancel it; my earlier plan still stands.', 'I did not say to withdraw my agreement.'], []),
 ('reported-relative', 'Who has offered to pay the balance?', ['My sister said she would pay {amount} on {date}.', '{name} told me they would make the payment; I have made no offer.', 'The promise to pay was made by my brother, not by me.'], ['reported_third_party']),
 ('reported-agent', 'What were you told about the charge?', ['The agent said this fee was wrong.', 'A representative told me the debit was a mistake.', '{name} at the service desk said the charge should be reversed.'], ['reported_third_party']),
 ('report-and-adopt', 'Is your relative making the payment, or are you?', ['My sister offered to pay, but I will personally send {amount} on {date}.', '{name} said they could help. I am now committing to pay {amount} myself.', 'My brother mentioned paying; my own plan is to send {amount} on {date}.'], ['proposal','reported_third_party']),
 ('report-withdraw-not-own', 'Has anyone changed their mind about their own agreement?', ['My brother withdrew his permission; I have not withdrawn anything.', '{name} said they canceled their earlier approval.', 'The other account holder said to stop their agreed debit.'], ['reported_third_party']),
 ('quote-hypothetical', 'Are you making a promise, or discussing an example?', ['If someone said "I will pay {amount}", would that count as a promise?', 'Suppose I paid on {date}; what would happen? This is only an example.', 'Hypothetically, what if a person offered to pay {amount}?'], ['uncertain']),
 ('report-tentative', 'What is the other account holder considering?', ['My sister might pay if her wages arrive.', '{name} is unsure whether they can make the payment.', 'My brother said perhaps he could pay on {date}.'], ['reported_third_party','uncertain']),
 ('deny-reported-promise', 'Did you yourself offer to pay, or did your colleague?', ['My colleague made that offer; I did not promise any payment.', 'That was {name} saying they would pay, not my own offer.', 'I am reporting someone else\'s promise; I have not adopted it.'], ['reported_third_party']),
 ('affirm-admin', 'Is {name} the person who should receive the statement?', ['Yes, that is the recipient.', 'Right, that is who should receive it.', 'Correct, you have the intended recipient.'], ['current_affirm']),
 ('affirm-explanation', 'Would you like me to explain how the statement is organized?', ['Yes, please explain it.', 'Right, an explanation would help.', 'Yes, I want the explanation.'], ['current_affirm']),
 ('mixed-withdraw-propose', 'You approved an automatic debit and also discussed a manual payment.', ['Withdraw my debit permission; I will instead pay {amount} manually on {date}.', 'Cancel my earlier automatic-payment approval. My own payment will be {amount}.', 'I revoke the automatic debit, but I commit to send {amount} myself.'], ['current_withdraw','proposal']),
 ('mixed-dispute-repair', 'You said the disputed charge was {old_amount}.', ['That amount is incorrect; the disputed charge is {amount}, not {old_amount}.', 'I meant {amount}. I still dispute the charge.', 'Correct the amount to {amount}; I contest that debit.'], ['dispute','correction']),
 ('mixed-affirm-dispute', 'Is this your account, even though you contest the charge?', ['Yes, it is my account, but the charge is not mine.', 'Correct, the account is mine. I dispute that purchase.', 'Yes to the account ownership; I still contest the debit.'], ['current_affirm','dispute']),
 ('unclear-referent', 'There are two proposed dates and two payment amounts.', ['Maybe that one, but I do not know which amount you mean.', 'It depends which of those options you are referring to.', 'I cannot tell what "that" refers to yet.'], ['uncertain']),
 ('amount-only-no-proposal', 'How much does the disputed statement show?', ['It shows {amount}.', 'The printed total is {amount}.', 'I can read {amount} on the statement.'], []),
 ('past-payment-not-future', 'What happened with the payment last month?', ['I sent {amount} last month.', 'The payment happened on {old_date}.', 'I paid it before this conversation.'], []),
 ('question-not-commitment', 'Do you want to ask about the payment options?', ['What would the fee be if I paid on {date}?', 'Can you explain whether installments have interest?', 'How does the payment schedule work?'], []),
 ('quoted-correction', 'What did the other customer say about the amount?', ['They said "I meant {amount}, not {old_amount}."', '{name} corrected their own figure to {amount}.', 'My colleague told you to replace their earlier amount.'], ['reported_third_party']),
 ('scope-two-obligations', 'We are discussing both the loan installment and a separate card fee.', ['I will pay the loan on {date}; I dispute only the card fee.', 'My offer of {amount} is for the loan. The unrelated fee is wrong.', 'The loan payment will be {amount}; I contest the separate card charge.'], ['proposal','dispute']),
 ('retract-future-promise', 'You had promised to make a payment on {date}.', ['I withdraw that promise; I cannot make the payment.', 'Cancel the plan I offered earlier.', 'I am retracting my earlier commitment to pay.'], ['current_withdraw']),
 ('conditional-retraction', 'You previously allowed an automatic debit.', ['If my wages do not arrive, I might withdraw that permission.', 'I may cancel my previous approval, but I have not decided yet.', 'Perhaps I will stop the earlier arrangement if the transfer fails.'], ['uncertain']),
 ('report-dispute-own-proposal', 'What did the other account holder say, and what will you do?', ['My brother says the fee is wrong. I will pay {amount} for my own balance.', '{name} disputes their charge; I will send {amount} for mine.', 'My sister contests her debit. My own payment will be on {date}.'], ['proposal','reported_third_party']),
 ('ordinary-negation', 'Do you need a copy of the statement?', ['No, I already have a copy.', 'No thanks, I can see the statement.', 'I do not need another copy.'], []),
]

# Context-dependent contrasts are one family, including synonymous short tokens.
SHORT = [
 ('Do you personally commit to paying {amount} on {date}?', 'yes', ['current_affirm','proposal']),
 ('Would you like an explanation of the account terms?', 'yes', ['current_affirm']),
 ('You previously permitted the debit. Do you now revoke that permission?', 'yes', ['current_affirm','current_withdraw']),
 ('Are you replacing your earlier proposed date with {date}?', 'yes', ['current_affirm','correction','proposal']),
 ('Are you only giving a hypothetical example, with no current commitment?', 'yes', ['current_affirm','uncertain']),
 ('Are you reporting your brother\'s promise, without adopting it yourself?', 'yes', ['current_affirm','reported_third_party']),
 ('Do you accept that this disputed purchase was yours?', 'no', ['dispute']),
 ('May I debit the account? You have given no permission so far.', 'no', []),
 ('You previously allowed the debit. Should I keep that permission active?', 'no', ['current_withdraw']),
 ('Have I correctly recorded the date you meant to propose?', 'no', ['correction']),
 ('Do you need the statement explained?', 'no', []),
 ('You meant checking instead of savings; is that correction accurate?', 'right', ['current_affirm','correction']),
 ('You are confirming only the address spelling; is that accurate?', 'right', ['current_affirm']),
 ('You personally promise to pay {amount}; is that accurate?', 'right', ['current_affirm','proposal']),
 ('You are withdrawing the permission you gave earlier; is that accurate?', 'right', ['current_affirm','current_withdraw']),
 ('Your colleague made that promise, and you are only reporting it; correct?', 'right', ['current_affirm','reported_third_party']),
 ('I understood you meant savings. Is that the account you meant?', 'not that', ['correction']),
 ('I will use your earlier permission for the automatic debit. Shall I do that?', 'not that', ['current_withdraw']),
 ('Was that posted purchase made by you?', 'not that', ['dispute']),
 ('Are you promising a payment now or just describing a possibility?', 'not that', ['uncertain']),
]

# Fresh CAL/EVAL use separate authored conversation constructions. Numeric and
# name substitutions cannot change their split. OOD consists of difficult text
# families and is not a claim about unseen human/customer distributions.
CAL = [
 ('invoice-escrow', 'The contractor asks what you intend for the invoice held in escrow.', ['I intend to release {amount} to settle the invoice on {date}.', 'My offer is a settlement payment of {amount} after the inspection.'], ['proposal']),
 ('rental-ownership', 'The rental invoice includes damage attributed to you.', ['The damage existed when I collected the vehicle; I contest that liability.', 'That rental damage charge is not my responsibility.'], ['dispute']),
 ('recipient-repair', 'I have recorded the refund recipient as the buyer.', ['The recipient should be the original payer, not the buyer; correct that.', 'You have the recipient wrong. I meant the person who paid.'], ['correction']),
 ('accessibility-assent', 'Should I read the invoice aloud using slower speech?', ['Yes, slower speech please.', 'That would help; yes.'], ['current_affirm']),
 ('escrow-retraction', 'You earlier instructed release of the escrow funds.', ['I now rescind that release instruction.', 'Put the release I approved on hold.'], ['current_withdraw']),
 ('pending-appeal', 'Are you settling the invoice before the appeal concludes?', ['I may settle if the appeal fails, but no decision yet.', 'It depends on the appeal; I cannot commit now.'], ['uncertain']),
 ('trustee-report', 'Who gave the instruction regarding the estate invoice?', ['The trustee said she would settle it.', 'I am passing on the trustee\'s words: she promised payment.'], ['reported_third_party']),
 ('settle-not-accept-liability', 'Will you pay the collection invoice?', ['I offer {amount} as a settlement while disputing liability.', 'I contest the debt but will send {amount} to end this matter.'], ['proposal','dispute']),
 ('withdraw-one-maintain-other', 'You approved both an invoice debit and delivery updates.', ['Revoke the invoice debit approval; keep the delivery updates.', 'I withdraw only my payment permission, while the update consent stands.'], ['current_withdraw']),
 ('historical-quote', 'Are those your own current instructions?', ['The old letter says "pay on {date}"; I am quoting it, not making that offer.', 'The administrator wrote that instruction; it is not my promise.'], ['reported_third_party']),
 ('hypothetical-installment', 'We are discussing an example repayment calculation.', ['Suppose I offered {amount}; how many installments would that be?', 'What if the fictional customer paid on {date}?'], ['uncertain']),
 ('partial-unknown', 'You mentioned two invoices but I missed which one you meant.', ['That invoice, the one after...', 'I mean the bill from the...'], ['uncertain']),
 ('cal-short-assent-scope', 'The mediator asks whether to explain the invoice appeal form, without offering any settlement.', ['yes', 'right'], ['current_affirm']),
 ('cal-short-withdraw-scope', 'You authorized release from escrow yesterday. Should that release instruction stay in force?', ['no', 'not that'], ['current_withdraw']),
 ('cal-short-correction-scope', 'The refund payee was the original payer; I mistakenly wrote the buyer. Are you confirming the payee correction?', ['yes', 'right'], ['correction','current_affirm']),
 ('cal-first-refusal', 'This is the first request for permission to release escrow funds.', ['no', 'I decline to give that permission.'], []),
 ('cal-date-mixed', 'You offered settlement after inspection and mentioned a disputed rental fee.', ['I meant {date} instead of {old_date}. I will pay {amount}, but the damage fee remains wrong.', 'Correct my settlement day to {date}; I still dispute the damage fee.'], ['proposal','correction','dispute']),
 ('cal-reported-with-adoption', 'The trustee and you have discussed separate portions of the invoice.', ['The trustee promised her portion. I will pay {amount} for mine.', 'She offered payment; I personally commit to my share on {date}.'], ['proposal','reported_third_party']),
 ('cal-no-current-act', 'Where is the appeal form on the page?', ['It is below the invoice total.', 'The form is on page two.'], []),
 ('cal-unknown-short', 'There were three unresolved offers, and the speaker has not said which one is intended.', ['that one', 'maybe the other'], ['uncertain']),
]

EVAL = [
 ('ood-double-negation', 'You had approved recurring payments. Are you retracting approval?', ['I am not saying I do not approve; leave my prior approval in place.', 'It is untrue that I have asked you to cancel it.'], []),
 ('ood-scope-reversal', 'You had permitted payment from two accounts.', ['Withdraw permission for the joint account only; the personal-account approval stands.', 'Keep the second approval, revoke the first one.'], ['current_withdraw']),
 ('ood-embedded-quote', 'Which words are yours and which came from the executor?', ['The executor said, "I will pay," and I replied, "That is your promise."', 'When he said "yes, pay it," he was speaking for himself. I am only reporting him.'], ['reported_third_party']),
 ('ood-negated-hypothesis', 'Do you personally undertake payment, or is this an imagined example?', ['Even if I could pay {amount}, it would still only be a what-if.', 'Pretend I offered payment on {date}; that is a thought experiment.'], ['uncertain']),
 ('ood-repair-before-denial', 'I wrote that you denied the fee, but you had been talking about the date.', ['No: I meant change the date to {date}, not deny the fee.', 'You repaired the wrong field. My correction concerns the date alone.'], ['correction']),
 ('ood-denial-before-repair', 'The merchant says your approval covered the disputed purchase.', ['Their claim is false. Do not call this a change of date; I contest making that purchase.', 'I deny approving that purchase, regardless of the date they printed.'], ['dispute']),
 ('ood-self-other-cross', 'Your colleague and you discussed separate invoices.', ['She disputes hers; I will pay mine on {date}.', 'His refusal is his own. My commitment is to pay {amount}.'], ['reported_third_party','proposal']),
 ('ood-quoted-withdrawal', 'Has your own earlier approval changed?', ['My partner said "revoke mine." I have made no such request.', 'The cancellation was his instruction, which I am reporting.'], ['reported_third_party']),
 ('ood-irregular-amount', 'What settlement do you offer for the disputed invoice?', ['I offer {amount}, though I contest the entire invoice.', 'Without accepting liability, my settlement offer is {amount}.'], ['proposal','dispute']),
 ('ood-overlapping-dates', 'You offered payment after the hearing and before the review.', ['Make it {date}, not {old_date}; I will pay then even though the fee is disputed.', 'I revise my payment day to {date}, while contesting the invoice.'], ['proposal','correction','dispute']),
 ('ood-elliptical-promise', 'What do you personally undertake after the inspection?', ['Payment of {amount} by me on {date}. That is my commitment.', 'My undertaking: {amount}, after inspection, on {date}.'], ['proposal']),
 ('ood-late-retraction', 'The recurring debit you previously approved has not yet run.', ['That prior approval is rescinded, effective now.', 'Treat the consent I gave as withdrawn from this point.'], ['current_withdraw']),
 ('ood-admin-short', 'A screen reader can spell the recipient name aloud. Shall it do so?', ['yes', 'right'], ['current_affirm']),
 ('ood-reported-short', 'Are the words "I undertake payment" from the executor\'s letter, with you merely quoting the executor?', ['yes', 'right'], ['current_affirm','reported_third_party']),
 ('ood-withdraw-short', 'You authorized a standing order last week. Shall I continue using that authorization for the next debit?', ['no', 'not that'], ['current_withdraw']),
 ('ood-correction-short', 'I transcribed the hearing date as the review date. Is that what you meant?', ['no', 'not that'], ['correction']),
 ('ood-hypothesis-short', 'You are imagining what would happen if someone paid, with no actual offer from you. Is that the intended scope?', ['yes', 'right'], ['current_affirm','uncertain']),
 ('ood-conditional-report', 'What is the executor considering after the hearing?', ['He might settle if the appeal fails; that is what he told me.', 'She said she may pay, provided the review is unfavorable.'], ['reported_third_party','uncertain']),
 ('ood-incomplete-switch', 'You first proposed a date, then started revising it.', ['Not the old day: the Tuesday following...', 'Replace it with the day before the...'], ['correction','uncertain']),
 ('ood-benign-no', 'Would you like a third copy of the invoice summary?', ['no', 'I have enough copies, thank you.'], []),
 ('ood-bare-question', 'What do you want to ask about the estate invoice?', ['Is there a deadline for an appeal?', 'Who can explain the estate accounting procedure?'], []),
 ('ood-ambiguous-target', 'Two permissions and two amounts were discussed, without a clear final referent.', ['The latter, or maybe the former, I am not certain.', 'I mean that other one, unless it was the first.'], ['uncertain']),
 ('ood-affirm-correct-recipient', 'I corrected the refund payee from purchaser to original payer. Does that now match your instruction?', ['yes', 'right'], ['current_affirm','correction']),
 ('ood-negated-withdraw-positive', 'You earlier instructed release of an escrow payment.', ['I am not merely asking about cancellation. I rescind my release instruction now.', 'Do not interpret this as a hypothetical: withdraw my prior approval.'], ['current_withdraw']),
]

SLOTS = [
 {'amount':'80 dollars','old_amount':'180 dollars','date':'November 5','old_date':'November 2','name':'Alex'},
 {'amount':'125 euros','old_amount':'225 euros','date':'December 12','old_date':'December 10','name':'Morgan'},
 {'amount':'300 lira','old_amount':'430 lira','date':'next Friday','old_date':'next Monday','name':'Sam'},
 {'amount':'47 pounds','old_amount':'97 pounds','date':'the 18th of March','old_date':'the 16th of March','name':'Taylor'},
 {'amount':'one hundred dollars','old_amount':'two hundred dollars','date':'2027-01-14','old_date':'2027-01-11','name':'Jordan'},
 {'amount':'62.50 euros','old_amount':'162.50 euros','date':'the second Tuesday in April','old_date':'the first Tuesday in April','name':'Casey'},
 {'amount':'900 yen','old_amount':'1900 yen','date':'three days after payday','old_date':'payday','name':'Riley'},
 {'amount':'250 dollars','old_amount':'350 dollars','date':'June 21','old_date':'June 20','name':'Jamie'},
]

def vectors(positives, unknown=()):
    return [int(k in positives) for k in LABELS], [k not in unknown for k in LABELS]
