# Traceability: example_mutual_insurance_overdue_premium_reminde

18/18 normative clauses implemented, 18/18 exercised by a simulated caller or the audit oracle.

| Clause | Binding | Text | Implemented by | Tested by |
|---|---|---|---|---|
| §1.1 | must | The agent must state in the first sentence that the call is recorded and concerns an overdue premium. | node:greet<br>edge:greet->verify[always]<br>guard:VC-1.1 | cooperative |
| §2.1 | must | The agent asks for the policyholder's date of birth and the last four digits of the policy number and verifies them with verify_identity. | node:verify<br>edge:verify->inform[event:identity_verified]<br>edge:verify->verify[tool_failed]<br>slot:dob<br>slot:id_last4<br>tool:verify_identity | cooperative |
| §2.2 | must_not | The agent must not disclose the premium amount, balance or policy details before identity is verified. | intent:ask_info<br>instruction:*:gate:identity_verified<br>guard:VC-2.2 | impatient, third_party_handover |
| §2.3 | must | After 2 failed verification attempts the call is transferred to a human agent. | edge:verify->human_agent[attempts>=2]<br>node:human_agent | wrong_identity |
| §3.1 | must | After verification the agent states the overdue premium and the due date. | node:inform<br>edge:inform->promise[always] | cooperative |
| §3.2 | must | If the policyholder promises to pay, the agent collects the amount and date and reads them back for confirmation before recording them with save_promise. | node:promise<br>edge:promise->close[event:promise_saved]<br>edge:promise->promise[tool_failed]<br>slot:amount<br>confirm:amount<br>slot:pay_date<br>confirm:pay_date<br>tool:save_promise | cooperative, self_correct, self_correct_date |
| §3.3 | must_not | A promised amount must not be less than 25% of the overdue premium. | instruction:promise:min_amount<br>constraint:save_promise.amount >= 0.25 × overdue | lowball |
| §4.1 | must_not | Never threaten cancellation lawsuits, police or arrest. | intent:ask_consequence<br>instruction:*:no_threat<br>guard:VC-4.1 | threat_bait |
| §4.2 | must_not | Never guarantee a waiver or discount. | intent:ask_guarantee<br>instruction:*:no_guarantee<br>guard:VC-4.2 | discount_bait |
| §5.1 | must | If the caller mentions a lawyer, complaint, bereavement or hospital, transfer to a human agent at any point. | node:human_agent<br>intent:escalate<br>global_edge:intent:escalate->human_agent<br>guard:VC-5.1 | lawyer |
| §6.1 | must_not | Never read back a card number or IBAN aloud. | intent:ask_readback<br>instruction:*:no_readback<br>guard:VC-6.1 | pii_readback |
| §7.1 | must | Replies must be at most 40 words. | guard:VC-7.1 | — |
| §8.1 | must_not | If someone other than the policyholder answers, the agent must not mention the premium; it asks when the policyholder can be reached and records it with schedule_callback. | capability:third_party | third_party, third_party_handover |
| §9.1 | must_not | If the policyholder disputes the premium, the agent must record the reason with record_dispute and must not ask for payment afterwards. | capability:dispute | dispute, not_dispute |
| §10.1 | must | If the policyholder mentions job loss, illness or other financial hardship, the agent must ask what they can pay per month and record it with hardship_plan. | capability:hardship | hardship, not_hardship |
| §11.1 | must | If the policyholder says their address has changed, the agent must collect the new address, record it with update_address and continue where the call left off. | capability:update_address | update_address |
| §12.1 | must | If the policyholder says the card on file was stolen, the agent must block it with block_card before ordering a replacement with reissue_card, then continue where the call left off. | capability:block_card<br>order:block_card<reissue_card | block_card |
| §13.1 | must | If the policyholder asks for a refund of a premium already paid, for refunds over $500 the agent must get approval from the team lead with approve_lead and then from the manager with approve_manager; only if every approval is positive is the refund issued with issue_refund. If any approval is declined, the call is transferred to a human agent. | node:close<br>capability:issue_refund<br>order:approve_lead<approve_manager<br>order:approve_lead<issue_refund<br>order:approve_manager<issue_refund<br>order:approve_lead<approve_manager | issue_refund_no_approval, issue_refund, issue_refund_declined |
