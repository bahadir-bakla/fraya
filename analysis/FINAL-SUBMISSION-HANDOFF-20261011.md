# Final delivery — Fraya

Email reply to yavuz@freyavoice.ai before 20:00 UTC / 23:00 Istanbul. User sends the reply.

Attach submission-final-20261011/submission.json, final.workflow.json and final.trace.jsonl. The trace is 3,064,440 bytes and includes the full actual original Codex generation and fresh refinement sessions without summarizing or replacing them. Also attach the Git archive requested by the user.

Builder source commit actually run: a6cd5c70fa4cc16d6e3787aa83f2de624eb071a5. The later delivery commit adds only packaging and evidence. submission.json preserves the actual builder source commit; the archive identifies its own delivery commit in COMMIT.txt. The run_command is a portable fresh-generation command; actual refinement invocation and source ancestry are in the full trace.

Final workflow bb f712b4 (full ID bbf712b4-a1f3-4e37-889d-27de91a87c3e), published version 2, actual exported bytes. No manual candidate edits. Freya fixed experimental-5.

Mock https://final-bank-mock.final-bank-mock.workers.dev remains deployed. Actual public617/617 fixture controls passed, including expected errors and delay.

Actual final authored platform outcomes: version1 0/5; version2 6/10 on one repetition each, 4 actual failures retained. FC01, FC03 and FC09 repeat nonfinancial no/done instead of leaving promptly; FC08 week-option dialogue fails. FC11 and FC12 not executed before delivery freeze. No claim of perfect or hidden-test success. MiniLM V3 is a separate prior research artifact and is not this final workflow version.

Suggested email body:
Hi Yavuz,
Please find Team Fraya's final submission attached: submission.json, the Freya-exported workflow, the full builder trace, and our source repository archive with its delivery commit recorded in COMMIT.txt. Our mock remains live at the URL in submission.json.
Members: Bahadır Selim Bakla and Yusuf Said Çöpçü.
Thank you.
