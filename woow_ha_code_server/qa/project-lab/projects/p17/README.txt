Procurement Quote Comparison (p17)
Run: node test.mjs. Import {meta, run} from ./app.mjs. The coordinator provides
the shared main.mjs/runtime.mjs server and interactive page.

Input: quantity (1..10000), deadlineDays (0..365), quotes (1..100).
Quote fields: unique supplier, unitPriceCents (0..10,000,000), leadDays (0..365).
Optional shippingCents (0..1,000,000,000, default 0), taxBasisPoints and
discountBasisPoints (0..10000, default 0), minimumQuantity and packSize
(1..10000, default 1). All numbers are integers. 100 basis points = 1 percent.
Order quantity is max(requested, minimum), rounded up to a pack. Discount is
applied to item subtotal, then shipping is added, then tax. Each basis-point
amount is rounded half-up using exact integer arithmetic. Cost per needed unit
is total / REQUESTED quantity, rounded to cents, so surplus units have a cost.
Eligible means leadDays <= deadlineDays. Rank eligible suppliers first, then
total cost, delivery speed, supplier name. No eligible quote returns null.

Worked example: need 10. Atlas: 100 cents each +100 shipping +5% tax =1155.
Beacon: 95 cents, packs of 6 =>12 units, total1140. Both meet deadline; Beacon
wins despite supplying two extra units. See meta.example for a complete input.

Limitations: one shared currency, one item, one shipment. Tax on shipping is a
stated calculation assumption, not tax advice. No supplier quality, exchange
rates, live quotes or procurement actions. Cases are independently hand-derived.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p17 .; podman run --rm -p 127.0.0.1:8080:8080 p17
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"quantity":10,"deadlineDays":7,"quotes":[{"supplier":"Atlas","unitPriceCents":100,"shippingCents":100,"taxBasisPoints":500,"leadDays":3},{"supplier":"Beacon","unitPriceCents":95,"packSize":6,"leadDays":5}]}
  output: {"quantity":10,"ranking":[{"supplier":"Beacon","orderQuantity":12,"excessQuantity":2,"subtotalCents":1140,"discountCents":0,"shippingCents":0,"taxCents":0,"totalCents":1140,"effectiveUnitCostCents":114,"leadDays":5,"eligible":true},{"supplier":"Atlas","orderQuantity":10,"excessQuantity":0,"subtotalCents":1000,"discountCents":0,"shippingCents":100,"taxCents":55,"totalCents":1155,"effectiveUnitCostCents":116,"leadDays":3,"eligible":true}],"recommendedSupplier":"Beacon"}
Supported limitation: One currency, one item, one shipment; no live quotes or supplier quality scoring.
