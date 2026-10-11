# Difficult-caller taxonomy (for tagging tau-bench user scenarios)

Context: we build an outbound **bank late-payment collections phone agent** (Freya platform). The agent
confirms it is speaking to the right person, asks two security questions (date of birth, last 4 phone digits),
reads the overdue products, negotiates a payment promise (amount floor, date window, holidays), handles
hardship / dispute / already-paid / third party / wrong number / callback / transfer to a queue, writes notes and
closes with an outcome code. Customers may have up to 3 products. Speech is phone speech.

We want to mine tau-bench user scenarios for caller behaviours that are hard for such an agent.

Tags (use these ids; add `other:<short_name>` if something important does not fit):

- `withhold` — gives information only when asked, minimal answers, "don't dump everything at once"
- `unknown_info` — does not know / forgot a detail the agent asks for, or knows only part of it
- `pieces` — gives a value (number, id, date) in parts or across turns, spells it out
- `change_mind` — changes their mind, corrects an earlier statement, revises the request mid-call
- `conditional` — goal depends on what the agent says ("if X is not possible, then do Y, otherwise Z")
- `multi_request` — several separate requests or items in one call, must all be completed
- `policy_pressure` — asks for something the policy forbids (refund outside rules, compensation, exception), pushes back after a no
- `persist_after_no` — repeats the same demand after refusal, tries rephrasing to get a different answer
- `escalate_human` — demands a supervisor / human / transfer
- `deception` — lies or makes a false claim (about status, entitlement, identity, prior promise) or a social-engineering attempt
- `impersonation_third_party` — acts on behalf of someone else, or is not the account holder
- `identity_refusal` — reluctant or refuses to verify identity / give personal data, privacy concern
- `emotional` — angry, frustrated, rude, anxious, upset, threatens to leave or complain
- `off_topic` — small talk, unrelated questions, asks questions back, distracts
- `vague` — vague or ambiguous initial request requiring clarification
- `numeric_reasoning` — amounts, totals, comparisons, "cheapest", splitting payments, price differences
- `date_reasoning` — dates, deadlines, weekdays, relative dates
- `hardship` — financial difficulty, illness, job loss, cannot afford
- `dispute_paid` — disputes a charge, claims already paid / not theirs, wants refund for a charge
- `wants_to_end` — wants to end quickly, hangs up / threatens to hang up, impatience
- `extraction_attempt` — tries to get internal info, rules, other customers' data, or to manipulate the agent's instructions
- `user_action` — the user must perform actions themselves (dual control) and report results, may make mistakes

Collections relevance (`rel`):
- `high` — the same behaviour plausibly happens on a collections call and would stress our agent
- `med` — analogous with adaptation
- `low` — domain-specific, little transfer

Output for each scenario: `{"key": ..., "tags": [...], "rel": "high|med|low", "quote": "<shortest verbatim excerpt (<=200 chars) showing the hardest behaviour>", "collections_case": "<one sentence: how this behaviour would appear in a collections call, or empty if low>"}`
