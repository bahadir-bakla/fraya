# The final case: Freya Bank, credit card statement debt

Freya Bank is fictional. Every customer, card, amount and address in this pack is synthetic.

## When

The case opens Sunday 11 October, 17:00 UTC (20:00 Istanbul). Submissions close Sunday 11 October, 20:00 UTC (23:00 Istanbul).

## The scenario

Freya Bank wants its phone line to answer one of its most common calls with a voice assistant: "how much is my credit card statement debt?". The caller has already passed the bank's phone menu (IVR). The menu has checked who they are and hands the call to the assistant with the customer number. The assistant finds the right card, reads the statement debt in Turkish lira, US dollars, euros and pounds sterling, and says when it is due.

In the same call the customer may want two more things: move their statement date to another week, or get the statement sent to the e-mail address the bank has on file. A customer who wants to pay or who asks for a person is handed to a human agent. The calls are in Turkish.

The bank did not write a clean specification. It sent what it had: an analysis document, the announcements its phone menu reads today, a flow drawing, service descriptions, an integration document, its mails to our team, a list of abbreviations and an FAQ. They were written months apart and they do not always agree.

## What you build

1. **First, your own mock of the bank's services**, on Cloudflare Workers. Same paths, same field names, same request and response shapes as the bank's integration document (section 6). For the bank's test customers it returns exactly the answers listed in the pack, HTTP status included. Deploy it before you run your builder and keep it running until the results are out: our simulated customers reach your mock through the tools in your workflow, so a Worker that is down fails those conversations.
2. **Then the phone agent, built by your builder.** Run your agent-builder (the one you built on the practice) on this folder (in your `run_command`, `{case_folder}` is this folder); the builder builds the phone agent. No manual edits to what it builds. You may fix bugs in your builder, but do not hard-code this case into it. The phone agent's tools call your mock. It runs on Freya LLM, the only model on staging. Every builder rule on the event page holds here too.

Every call gives the phone agent two variables:

- `customerNumber`: the 8-digit customer number from the phone menu. The agent never asks for it.
- `now`: the date and time of the call, Istanbul time, for example `2026-10-12T10:30:00+03:00`. Every date decision uses `now`, never the system clock.

## Inputs

- `README.md`: the pack overview: what each folder is, the two variables.
- `statement-debt-call-flow.pdf`: a call-flow drawing of the step.
- `sources/emails/`: mail threads between the bank and our team, with the bank's analysis documents in `attachments/`.
- `sources/documents/`: what the bank handed over: the phone-menu prompt sheet, the service contract and a page from the bank's website.
- `sources/meetings/`: transcript excerpts from meetings with the bank.
- `test-environment/`: the bank's test customers (`test-customers.md`, `test-customers.json`) your mock must serve.
- `example-scenarios.md`: six example conversations (two ordinary, two edge, two adversarial) of the kind we score with. The rest stay hidden.
- `cloudflare-mock/`: how to run and deploy a Worker, with a one-endpoint example. The bank's services you write yourself.

## How you are scored

Your phone agent is tested with simulated customers you never see. The workflow your builder made is reviewed too. In the simulations your agent's tools call your mock, so a wrong or unreachable mock fails those conversations. Traces are not scored; we read them to check the agent came out of your builder without hand edits.

## What you submit

One `submission.json`: the workflow your builder made, the trace of that builder run (paths relative to the repo) and the address of your mock.

```json
{
  "team": "Your team name",
  "members": [{ "name": "Ayşe Yılmaz", "email": "ayse@example.com" }],
  "repo": "https://github.com/your-team/your-builder",
  "commit": "the commit you ran",
  "run_command": "the command that runs your builder on this folder",
  "workflow": "submission/final.workflow.json",
  "trace": "traces/final.log",
  "mock_url": "https://your-mock.your-subdomain.workers.dev"
}
```

E-mail `submission.json`, the exported workflow and the trace to yavuz@freyavoice.ai before Sunday 11 October, 20:00 UTC (23:00 Istanbul).
