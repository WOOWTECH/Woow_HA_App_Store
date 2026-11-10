Fulfillment Allocation (p18)
Run: node test.mjs; import {meta, run} from ./app.mjs. The coordinator supplies
the shared main.mjs/runtime.mjs HTTP interface and UI.

Input: stock (1..100 unique {sku,quantity}, integer quantity 0..1,000,000), orders
(0..100). Order fields: unique id, priority (1..5, 1 highest), optional boolean
allowPartial (default false), lines (1..50 unique {sku,quantity}, 1..1,000,000).
Every line SKU must exist in stock, even if that stock is zero.
Orders run by priority then original input order. Without allowPartial, any
short line backorders the WHOLE order and consumes no inventory. Later orders
can use that stock. With allowPartial, each line receives up to available stock.
Results list only positive allocated/backordered quantities, order status,
remaining stock in original SKU order and conservation totals. No input mutation.

Worked example: stock A=5/B=2. High priority wants A=3/B=2 and receives both.
Lower priority wants A=4, disallows partial: backorder all four, leave A=2/B=0.
For A=5 and a partial-enabled request of seven, allocate five, backorder two.
See meta.example for the complete runnable priority example.

Limitations: single warehouse snapshot, no reservations, replenishment, shipping,
fair-share optimization or persistent stock updates. Synthetic planning only.
Tests use hand-derived allocations, conservation totals and invalid inputs.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p18 .; podman run --rm -p 127.0.0.1:8080:8080 p18
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: partial fulfillment consumes available stock.
Input: {"stock":[{"sku":"A","quantity":5}],"orders":[{"id":"O","priority":1,"allowPartial":true,"lines":[{"sku":"A","quantity":7}]}]}
Expected output: {"orders":[{"id":"O","priority":1,"status":"partial","allocated":[{"sku":"A","quantity":5}],"backordered":[{"sku":"A","quantity":2}]}],"remainingStock":[{"sku":"A","quantity":0}],"totals":{"requestedUnits":7,"allocatedUnits":5,"backorderedUnits":2,"fulfilledOrders":0}}
Supported limitation: Single warehouse snapshot; no replenishment or persistent stock updates.
