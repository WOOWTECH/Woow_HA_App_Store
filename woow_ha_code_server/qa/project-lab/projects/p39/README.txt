Safe arithmetic expression calculator

Purpose: Evaluate a bounded numeric expression using an explicit tokenizer and
recursive-descent parser. It never uses eval, Function, a shell, or dynamic
module loading. Only the fixed grammar below is accepted.

Input: {"expression":"(12.5 + 7.5) * 3 - 2^3^2 / 16"}
expression must be a nonempty string <=1000 characters and <=512 tokens.
Whitespace is ignored. Decimal forms include 12, 12., .5, 1.25, and 1e-3.
Numbers and intermediate results must be finite with magnitude <=1e100.
Recursive unary/power/parenthesis nesting is limited to 128 levels.

Grammar (highest-level rule first):
  sum     = product (('+' | '-') product)*
  product = unary (('*' | '/' | '%') unary)*
  unary   = ('+' | '-') unary | power
  power   = primary ('^' unary)?
  primary = number | '(' sum ')'

Powers associate right: 2^3^2 = 512. Power binds above a unary minus:
-2^2 = -4, (-2)^2 = 4, and 2^-3 = 0.125. Multiplication/division/remainder
and addition/subtraction associate left within their precedence levels.
% is JavaScript signed remainder, not percentage or mathematical modulo.
Division/remainder by zero, non-real powers, overflow, identifiers, function
calls, missing operands, and implicit multiplication are rejected with errors.
0^0 follows floating-point exponentiation and gives 1.

Worked example above: 20*3 - 512/16 = 28. Output includes trimmed expression
and result. Result is rounded to 12 significant digits, so 0.1+0.2 displays 0.3.

Limitations: IEEE-754 arithmetic, not arbitrary precision; underflow may yield
zero. No variables, functions, units, assignments, factorial, or bit operations.
The ^ operator means exponentiation. The ** spelling is not supported.

Running and integration:
From this project directory, run: node test.mjs
No installation, external dependencies, network, credentials, or persistent
storage are required. app.mjs exports meta and synchronous run(input).
The shared interactive UI, runtime.mjs, package.json, and HTTP server entry
are supplied by the coordinator under CONTRACT.txt; this batch owns only
app.mjs, cases.json, test.mjs, and this README.txt.

cases.json contains independent, manually derived complete expected outputs
and rejection fixtures. test.mjs checks them with node:assert/strict, verifies
useful errors, input immutability, JSON serialization and deterministic results,
and smoke-tests meta.example. A mismatch exits nonzero.

To call the standalone computation directly from this directory:
node --input-type=module -e 'import {meta,run} from "./app.mjs"; console.log(JSON.stringify(run(meta.example),null,2))'

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p39 .; podman run --rm -p 127.0.0.1:8080:8080 p39
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (pi)
Example input: {"expression":"(8-2)^2 / 3"}
Expected result: 12.
Supported limitation: floating-point arithmetic only; variables and function calls are rejected.
