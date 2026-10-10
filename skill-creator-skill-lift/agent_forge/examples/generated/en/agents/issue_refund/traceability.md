# Traceability: example_mutual_insurance_overdue_premium_reminde__issue_refund

9/18 normative clauses implemented, 6/18 exercised by a simulated caller or the audit oracle.

| Clause | Binding | Text | Implemented by | Tested by |
|---|---|---|---|---|
| §1.1 | must | The agent must state in the first sentence that the call is recorded and concerns an overdue premium. | — | — |
| §2.1 | must | The agent asks for the policyholder's date of birth and the last four digits of the policy number and verifies them with verify_identity. | node:verify<br>edge:verify->issue_refund[event:identity_verified]<br>edge:verify->verify[tool_failed]<br>slot:dob<br>slot:id_last4<br>tool:verify_identity | — |
| §2.2 | must_not | The agent must not disclose the premium amount, balance or policy details before identity is verified. | intent:ask_info<br>instruction:*:gate:identity_verified<br>guard:VC-2.2 | — |
| §2.3 | must | After 2 failed verification attempts the call is transferred to a human agent. | edge:verify->human_agent[attempts>=2]<br>node:human_agent | — |
| §3.1 | must | After verification the agent states the overdue premium and the due date. | — | — |
| §3.2 | must | If the policyholder promises to pay, the agent collects the amount and date and reads them back for confirmation before recording them with save_promise. | — | — |
| §3.3 | must_not | A promised amount must not be less than 25% of the overdue premium. | — | — |
| §4.1 | must_not | Never threaten cancellation lawsuits, police or arrest. | intent:ask_consequence<br>instruction:*:no_threat<br>guard:VC-4.1 | — |
| §4.2 | must_not | Never guarantee a waiver or discount. | intent:ask_guarantee<br>instruction:*:no_guarantee<br>guard:VC-4.2 | — |
| §5.1 | must | If the caller mentions a lawyer, complaint, bereavement or hospital, transfer to a human agent at any point. | node:human_agent<br>intent:escalate<br>global_edge:intent:escalate->human_agent<br>guard:VC-5.1 | — |
| §6.1 | must_not | Never read back a card number or IBAN aloud. | intent:ask_readback<br>instruction:*:no_readback<br>guard:VC-6.1 | — |
| §7.1 | must | Replies must be at most 40 words. | guard:VC-7.1 | — |
| §8.1 | must_not | If someone other than the policyholder answers, the agent must not mention the premium; it asks when the policyholder can be reached and records it with schedule_callback. | — | — |
| §9.1 | must_not | If the policyholder disputes the premium, the agent must record the reason with record_dispute and must not ask for payment afterwards. | — | — |
| §10.1 | must | If the policyholder mentions job loss, illness or other financial hardship, the agent must ask what they can pay per month and record it with hardship_plan. | — | — |
| §11.1 | must | If the policyholder says their address has changed, the agent must collect the new address, record it with update_address and continue where the call left off. | — | — |
| §12.1 | must | If the policyholder says the card on file was stolen, the agent must block it with block_card before ordering a replacement with reissue_card, then continue where the call left off. | — | — |
| §13.1 | must | If the policyholder asks for a refund of a premium already paid, for refunds over $500 the agent must get approval from the team lead with approve_lead and then from the manager with approve_manager; only if every approval is positive is the refund issued with issue_refund. If any approval is declined, the call is transferred to a human agent. | node:issue_refund<br>edge:issue_refund->issue_refund__approve_lead[slot:request_amount>500]<br>edge:issue_refund->issue_refund__direct[slots_filled]<br>node:issue_refund__approve_lead<br>edge:issue_refund__approve_lead->issue_refund__approve_manager[event:approve_lead_done]<br>edge:issue_refund__approve_lead->human_agent[tool_failed]<br>node:issue_refund__approve_manager<br>edge:issue_refund__approve_manager->issue_refund__issue_refund[event:approve_manager_done]<br>edge:issue_refund__approve_manager->human_agent[tool_failed]<br>node:issue_refund__issue_refund<br>edge:issue_refund__issue_refund->done[event:issue_refund_done]<br>edge:issue_refund__issue_refund->human_agent[tool_failed]<br>node:issue_refund__direct<br>edge:issue_refund__direct->done[event:issue_refund_done]<br>edge:issue_refund__direct->human_agent[tool_failed]<br>node:done<br>slot:request_amount<br>tool:approve_lead<br>tool:approve_manager<br>tool:issue_refund | — |
