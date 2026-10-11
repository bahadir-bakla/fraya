# Freya Bank: credit card statement debt

This folder is the final case. The task is in `BRIEF.md`.

Freya Bank is fictional. Every customer, card, amount, address and person in this folder is made up.

## What is here

- `statement-debt-call-flow.pdf`: a call-flow drawing of the step.
- `sources/emails/`: mail threads between Freya Bank and our team. The bank's analysis documents are in `sources/emails/attachments/`.
- `sources/documents/`: what the bank handed over: the phone-menu prompt sheet, the service contract and a page from the bank's website.
- `sources/meetings/`: transcript excerpts from meetings with the bank.
- `test-environment/`: the test customers your mock serves (`test-customers.json`, and the same data as a table in `test-customers.md`).
- `example-scenarios.md`: six example calls of the kind we score with.
- `cloudflare-mock/`: how to deploy a Cloudflare Worker, with a one-endpoint example.

The sources were written at different times by different people. They do not always agree.

## The two call variables

Every call reaches the assistant with:

- `customerNumber`: the 8-digit customer number. The phone menu has already identified the caller.
- `now`: the date and time of the call, Istanbul time, e.g. `2026-10-12T10:30:00+03:00`.

The calls are in Turkish.
