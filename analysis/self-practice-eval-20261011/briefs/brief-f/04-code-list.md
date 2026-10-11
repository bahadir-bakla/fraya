LAKESHORE MUTUAL - CASE SYSTEM
Close codes, outbound arrears (export 09-10-2026, table CLS_OUT_ARR)

close_call takes the outcome value and the reason code. Outcomes "promise" and "paid" take no reason code.

| outcome      | reason code | description                                   | ACS-7 / memo ref      | status  |
|--------------|-------------|-----------------------------------------------|-----------------------|---------|
| promise      | (none)      | at least one promise recorded                 | 12.2                  | active  |
| paid         | (none)      | every account reported already paid           | 12.3, 11.1            | active  |
| transferred  | XRS         | transferred, restructuring queue              | 11.3                  | active  |
| transferred  | XHU         | transferred, general queue (asked for person) | 11.4                  | active  |
| transferred  | XSP         | transferred, support queue (vulnerability)    | CM-2026-19 item 4     | active  |
| no_promise   | NDS         | dispute                                       | 11.2, 12.3            | active  |
| no_promise   | NHD         | hardship                                      | 9.5                   | RETIRED 12-10-2026 (see CM-2026-19 item 4) |
| no_promise   | NSE         | service error                                 | 10.4, 12.3            | active  |
| no_promise   | NRF         | refused                                       | 9.4, 8.4, 11.5        | active  |
| no_promise   | NPP         | partial payment taken                         | -                     | RETIRED 2025, do not use |
| not_verified | VFL         | verification failed                           | 5.4                   | active  |
| not_verified | VDC         | verification declined                         | 5.5, 11.5             | active  |
| not_reached  | RCB         | callback booked                               | 4.2 / CM item 1       | active  |
| not_reached  | RNC         | no callback possible                          | 4.3                   | active  |
| not_reached  | RWN         | wrong number                                  | 4.4                   | active  |
| not_reached  | RDC         | deceased                                      | 4.5                   | active  |
| not_reached  | RUC         | not confirmed / unclear                       | 3.3                   | active  |

Account note reasons (add_note "reason" field, one note per account without a promise):

| reason        | used for                         |
|---------------|----------------------------------|
| refused       | 8.4, 9.4, 11.5                   |
| hardship      | 9.5 (not written after CM-2026-19 item 4) |
| dispute       | 11.2                             |
| paid          | 11.1                             |
| service_error | 10.4                             |

Transfer queues (transfer_to_agent "queue"): restructuring, general, support.
