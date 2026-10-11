KESTREL MUTUAL – CRM CLOSING CODE LIST
Arrears outbound calls (automated channel)
**Revision 15 September 2026** – maintained by the CRM Team

The CRM accepts a call only when its outcome and reason code are taken from this list. `outcome` and `reason` are sent on `close_call`. Codes are sent exactly as written, in capitals. For outcomes marked "(no code)" no reason is sent.

---

**Table A – Product note reasons** (`add_note`, one per product without a recorded arrangement; see CP-7 7.12)

| CRM label | `reason` value to send | Used for |
|---|---|---|
| REF | `refused` | attempts used up (7.8.3), floor refused (7.7.5), deadline refused (7.6.6), does not wish to talk (7.11.8) |
| HSH | `hardship` | financial hardship (7.9.3) |
| DSP | `dispute` | dispute (7.11.2) |
| PD | `paid` | payment already made (7.11.1) |
| SYS | `service_error` | arrangement could not be recorded after three calls (7.10.3) |

---

**Table B – Call outcomes and reason codes**

| `outcome` | Reason code | Use when |
|---|---|---|
| `promise` | (no code) | at least one arrangement was recorded and the call was not transferred |
| `paid` | (no code) | no arrangement recorded and every product is noted `paid` |
| `transferred` | `XFER-RESTR` | transfer to queue `restructuring` (7.11.4) |
| `transferred` | `XFER-AGENT` | transfer to queue `general` (7.11.3) |
| `transferred` | `XFER-SUPP` | transfer to queue `support` (7.9.4) |
| `no_promise` | see Table C | no arrangement recorded, not transferred, and not every product noted `paid` |
| `not_verified` | `NV-FAIL` | verification failed (7.4.4) |
| `not_verified` | `NV-REFUSE` | member declined verification (7.4.5, 7.11.8) |
| `not_reached` | `NR-CB` | third-party callback booked (7.3.3) |
| `not_reached` | `NR-NOCB` | third party, no callback booked (7.3.3) |
| `not_reached` | `NR-WRONG` | wrong number (7.3.4) |
| `not_reached` | `NR-DECEASED` | member deceased (7.3.5) |
| `not_reached` | `NR-UNCLEAR` | identity of the person answering not confirmed (7.2.3) |

A transfer always closes as `transferred`, even when arrangements were recorded earlier in the call.

---

**Table C – Reason code for `no_promise`**

Look only at the notes that are not `paid`. Take the reason with the highest priority among them (1 is highest), whatever the order of the products:

| Priority | Note reason present | Reason code |
|---|---|---|
| 1 | `dispute` | `NP-DIS` |
| 2 | `hardship`, and a Financial Support callback was booked (7.9.2) | `NP-HCB` |
| 2 | `hardship`, no callback booked | `NP-HSHP` |
| 3 | `service_error` | `NP-SYS` |
| 4 | `refused` | `NP-RTP` |

Example: card noted `paid`, personal loan noted `refused`, car loan noted `dispute` → `no_promise` / `NP-DIS`.
