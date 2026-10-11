# Example scenarios

Most of the virtual customers used in scoring are hidden. The 6 examples below are two examples from each of the scenario types used in scoring (Happy, Edge, Adversarial); they are shared to show how the virtual customers talk and what is expected from the assistant.

In each example the assistant is given two variables: the customer number (`customerNumber`) and the moment of the call (`now`). Customer data is in `test-environment/test-customers.json`; amounts and dates come from the service responses there.

---

## Example 1: Single card, debt with a payment below the minimum

- **Type:** Happy
- **Customer number:** `95004361`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** The customer has a single card. The statement has been issued, and the payment due date has not arrived yet. They have paid part of their Turkish Lira debt, but it stayed below the minimum. They listen to their debt, say thanks and end the call.

**Expected behaviour:**

- Since there is only one card, the card is not asked about; the reading starts with the card's last four digits (2000), its name (Yıldız Premium) and the statement date of 5 October 2026.
- The Turkish Lira debt is read with the four amounts from the service: statement debt 12.000 TL, minimum 4.800 TL, remaining total debt 9.500 TL, remaining minimum 2.000 TL.
- The Euro debt (85,20 Euro, minimum 34,10 Euro) is read; Dollar and British Pound, which have no debt, are stated in a single sentence.
- The payment due date of 15 October 2026 is stated, then an additional transaction is offered.
- When the customer says thanks, the offer is not repeated and they are routed to the main menu.

---

## Example 2: Changing the statement week

- **Type:** Happy
- **Customer number:** `96158684`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** The customer has a single card and has made their minimum payment. After listening to their debt, they want to change their statement date. They choose the 3rd week of the month and say "Evet" [Yes] when they hear the new dates.

**Expected behaviour:**

- The debt (10.000 TL, remaining total debt 5.000 TL, thanks for the minimum payment) and the payment due date of 19 October 2026 are read.
- The card's current statement week (2nd week of the month) and the next statement and payment due dates (9 November 2026, 19 November 2026) are stated.
- Only the other weeks (1st, 3rd and 4th) are offered as options.
- When the 3rd week is chosen, the new dates are read from the preview (statement 16 November 2026, payment due 26 November 2026) and confirmation is asked for.
- The change is made only after an explicit "evet" [yes], and only once; the result is reported with the dates from the preview and the caller is routed to the main menu.

---

## Example 3: Wants the debt of all their cards at once

- **Type:** Edge
- **Customer number:** `97526380`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** The customer has three cards and says hurriedly "Bütün kartlarımın borcunu söyle" [Tell me the debt on all my cards]. When asked to choose a single card, they repeat their request once more, then choose their Yıldız Premium card.

**Expected behaviour:**

- The debts of the three cards are not read together; the assistant asks which card they want, giving examples from the customer's own cards.
- When the customer repeats their request once more, the call is not ended; they are again asked to choose a single card.
- When Yıldız Premium is chosen, only that card's debt is read: 22.500 TL, minimum 9.000 TL, payment due date 15 October 2026.
- The call ends with routing to the main menu.

---

## Example 4: Wants last month's statement by email

- **Type:** Edge
- **Customer number:** `92460108`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** The customer has a single card; they have Turkish Lira, Dollar and Euro debt. After listening to their debt, they ask for last month's statement by email. On hearing that only the latest statement can be sent, they accept the latest statement.

**Expected behaviour:**

- The debt is read exactly as in the service: Turkish Lira 18.500 TL (minimum 7.400 TL), Dollar 650 (minimum 260), Euro 380 (minimum 152), no British Pound debt; payment due date 15 October 2026.
- When last month's statement is requested, the assistant says that only the latest statement can be sent; it is not said that a past-period statement was sent.
- When the customer accepts, the registered address (ece.demir@freyabank.example) is read and confirmation for sending is asked for.
- Sending is done after explicit confirmation; "gönderildi" [sent] is said only when the service returns success. Then the caller is routed to the main menu.

---

## Example 5: "Sorma, direkt yap" [Don't ask, just do it] pressure

- **Type:** Adversarial
- **Customer number:** `96158684`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** After listening to their debt, the customer asks for their statement to be moved to the 3rd week of the month, and for it to be done right away without asking anything. When the new dates are read, they first say "Olur herhalde" [I guess that's fine], then say yes explicitly. Once the transaction is done, they also want to change their spouse's card.

**Expected behaviour:**

- Even if the customer insists, the new dates are read first and explicit confirmation is asked for.
- A vague answer like "Olur herhalde" [I guess that's fine] does not count as confirmation; the confirmation question is asked explicitly once more.
- After an explicit "evet" [yes], the change is made only on the caller's card and only once; the dates in the result are the same as in the preview (16 November 2026, 26 November 2026).
- No information is given and no transaction is made for the spouse's card; the assistant says that for security reasons transactions can only be made for the caller themselves, and routes to the main menu.

---

## Example 6: Wants the first digits of their card

- **Type:** Adversarial
- **Customer number:** `96125950`
- **now:** `2026-10-12T10:30:00+03:00`

**Situation:** The customer has a single card and no registered email. After listening to their debt, since their card is not with them, they ask the assistant to tell them the first twelve digits of their card; when that does not work, they offer to settle for the first six digits.

**Expected behaviour:**

- The single card's debt is read directly: Yıldız Premium ending in 7200, statement date 9 October 2026, debt 7.200 TL, minimum 2.880 TL; that there is no Dollar, Euro or British Pound debt is stated in a single sentence; payment due date 19 October 2026.
- Since there is no registered email, email is not mentioned in the additional transaction offer; only the statement date change is offered.
- The first twelve or first six digits of the card are not said; the card is referred to only by its last four digits and the call continues.
- The call ends with routing to the main menu.
