Token Bucket Rate-Limit Simulator

Purpose: Simulate a single supplied token bucket deterministically. No clocks,
network calls or real rate-limit enforcement. Run: node test.mjs. API: run(meta.example).

Fields: capacity (0.001–1000000), refillPerSecond (0–1000000), optional
initialTokens (0–capacity; default full), requests (up to 1000 {atMs,cost} events).
Amounts allow at most three decimal places. cost is 0.001–1000000. atMs is an
integer 0–86400000, nondecreasing; ties execute in supplied order. Time begins at
zero. Unknown fields and invalid amounts/timestamps throw errors.

Worked example: capacity=5, refillPerSecond=2; costs 4 at 0ms, 3 at 500ms and
3 at 1000ms yield accepted/rejected/accepted with final balance zero. The rejected
request has two tokens and retryAfterMs=500. Denials never deduct tokens.

Each event returns tokensBefore, tokensAfter, accepted and retryAfterMs. Accepted
requests have retryAfterMs=0; impossible requests (cost above capacity or no
refill) have null. Other delays are rounded up to the earliest whole millisecond
assuming no intervening consumption. Refill caps at capacity; idle bursts cannot
accumulate excess tokens. Final balance is at the last request, not a later time.

Integer microtokens represent all permitted amounts/refill exactly at millisecond
resolution; multiplication clamps before overflow. Empty requests preserve the
initial balance. Limitations: one bucket, no distributed coordination or queues.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p29 .; podman run --rm -p 127.0.0.1:8080:8080 p29
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: fractional tokens and impossible oversized request.
Input: {"capacity":1,"initialTokens":0,"refillPerSecond":0.5,"requests":[{"atMs":1000,"cost":0.5},{"atMs":1000,"cost":0.25},{"atMs":5000,"cost":2}]}
Expected output: {"accepted":1,"rejected":2,"finalTokens":1,"events":[{"atMs":1000,"cost":0.5,"accepted":true,"tokensBefore":0.5,"tokensAfter":0,"retryAfterMs":0},{"atMs":1000,"cost":0.25,"accepted":false,"tokensBefore":0,"tokensAfter":0,"retryAfterMs":500},{"atMs":5000,"cost":2,"accepted":false,"tokensBefore":1,"tokensAfter":1,"retryAfterMs":null}]}
Supported limitation: One simulated bucket only; no distributed coordination or enforcement.
