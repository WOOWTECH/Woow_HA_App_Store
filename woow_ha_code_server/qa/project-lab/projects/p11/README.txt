Inventory Reorder Planner (p11)
Run: node test.mjs. Import {meta, run} from ./app.mjs for standalone use.
The coordinator supplies the common main.mjs/runtime.mjs HTTP interface.

Input: reviewDays (integer 0..365), items (1..100). Each item requires a unique
sku, onHand (0..1,000,000), dailyUsage (0..10,000 whole units/day), leadDays
(0..365). Optional incoming, safetyStock, minimumOrder default to 0 (maximum
1,000,000); packSize defaults to 1 (1..100,000). Unknown fields are rejected.
Stock position = onHand + incoming. Trigger = usage * leadDays + safetyStock.
Target = usage * (leadDays + reviewDays) + safetyStock. At or below the trigger,
a positive target shortage is raised to the minimum order and rounded up to a
whole pack. Above the trigger, no order is placed. Projected stock includes
incoming and the proposed order. daysOnHand uses physical stock only, rounded
to two decimals; zero usage gives null. Results preserve item order.

Worked example: FILTER has 10 on hand + 5 incoming, consumes 5/day, lead 3 days,
safety 5, review 7: trigger 20, target 55, shortage 40. Packs of 12 mean order
48, projected stock 63. See meta.example and cases.json for complete inputs.

Limitations: deterministic demand, incoming assumed available, no expiration,
backorders, cost optimization or supplier capacity. Synthetic planning tool.
Fixtures are independently hand-derived and include boundaries and bad input.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p11 .; podman run --rm -p 127.0.0.1:8080:8080 p11
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"reviewDays":7,"items":[{"sku":"FILTER","onHand":10,"incoming":5,"dailyUsage":5,"leadDays":3,"safetyStock":5,"packSize":12,"minimumOrder":24},{"sku":"GLOVE","onHand":80,"dailyUsage":4,"leadDays":5}]}
  output: {"items":[{"sku":"FILTER","stockPosition":15,"reorderPoint":20,"targetStock":55,"orderQuantity":48,"projectedStock":63,"daysOnHand":2,"status":"reorder"},{"sku":"GLOVE","stockPosition":80,"reorderPoint":20,"targetStock":48,"orderQuantity":0,"projectedStock":80,"daysOnHand":20,"status":"sufficient"}],"totalOrderUnits":48,"reorderCount":1}
Supported limitation: Deterministic demand only; no expiry, backorders, cost optimization or supplier capacity.
