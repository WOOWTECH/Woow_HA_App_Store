Expense Splitting Ledger (p14)
Run: node test.mjs. Import {meta, run} from ./app.mjs. Coordinator supplies the
shared HTTP main.mjs/runtime.mjs entry and UI.

Input: members (1..50 unique names); expenses (0..200), each with unique id,
paidBy (known member), amountCents (integer 1..1,000,000,000). Optional split
is 1..50 unique {member,weight} entries, with integer weights 1..10,000.
Omitting split shares among every member equally. Every amount uses one shared
currency in integer cents. Unknown fields/references and fractional money fail.
Each share is floored, then remaining cents go to descending fractional
remainders, ties by members order. Result shares use members order. Positive
balance means that member should receive money. Negative means they owe.
Suggested transfers pair debtors and creditors in members order and settle all
balances exactly. They do not execute payments or minimize transfer count.

Worked example: A pays 3000 for A/B/C; B pays 1500 for A/B. Paid minus owed is
A +1250, B -250, C -1000. Transfers: B -> A 250; C -> A 1000. A 100-cent expense
shared three ways is 34/33/33. meta.example is a complete runnable sample.

Limitations: no refunds, tax treatment, exchange rates, payment tracking or
financial advice. All data is synthetic. Fixtures are independently derived.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p14 .; podman run --rm -p 127.0.0.1:8080:8080 p14
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"members":["Ada","Ben","Chen"],"expenses":[{"id":"Dinner","paidBy":"Ada","amountCents":3000},{"id":"Taxi","paidBy":"Ben","amountCents":1500,"split":[{"member":"Ada","weight":1},{"member":"Ben","weight":1}]}]}
  output: {"expenses":[{"id":"Dinner","paidBy":"Ada","amountCents":3000,"shares":[{"member":"Ada","amountCents":1000},{"member":"Ben","amountCents":1000},{"member":"Chen","amountCents":1000}]},{"id":"Taxi","paidBy":"Ben","amountCents":1500,"shares":[{"member":"Ada","amountCents":750},{"member":"Ben","amountCents":750}]}],"balances":[{"member":"Ada","paidCents":3000,"owedCents":1750,"balanceCents":1250},{"member":"Ben","paidCents":1500,"owedCents":1750,"balanceCents":-250},{"member":"Chen","paidCents":0,"owedCents":1000,"balanceCents":-1000}],"settlements":[{"from":"Ben","to":"Ada","amountCents":250},{"from":"Chen","to":"Ada","amountCents":1000}],"totalCents":4500}
Supported limitation: Integer cents only; no refunds, tax, exchange rates or payment tracking.
