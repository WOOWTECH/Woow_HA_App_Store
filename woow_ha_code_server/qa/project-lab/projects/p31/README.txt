Flashcard quiz scorer

Purpose: Grade a synthetic flashcard quiz, allowing answer aliases and optional
weights. Return counts, points, percent, a per-card explanation, and review IDs.

Input object:
- cards: 1–200 objects. Each has a unique trimmed id (1–80 characters), prompt
  (1–1000 characters), and answers (1–20 nonempty strings, each <=1000 characters).
- weight on a card: optional finite number 0.01–1000; defaults to 1.
- responses: object keyed by known card ID, values strings <=2000 characters.
  Omitted IDs or whitespace-only strings are unanswered. Unknown IDs are errors.
- caseSensitive: optional boolean, default false.

Answers use Unicode NFKC normalization, trimmed/collapsed whitespace, and by
 default lowercase comparison. Accepted aliases are exact matches after those
steps. Weights affect points and percentage, not the count of correct cards.
No partial credit. Results preserve original answer text. Review IDs retain
card order and include incorrect and unanswered cards. Points round to four
decimals; percentage rounds to two.

Worked example:
{"cards":[{"id":"a","prompt":"Capital?","answers":["Tokyo","東京"],"weight":2},{"id":"b","prompt":"2+2?","answers":["4"]}],"responses":{"a":" tokyo ","b":"5"}}
This earns 2 of 3 points (66.67%), with one correct and one incorrect answer.
The review list is ["b"].

Limitations: No fuzzy matching, semantic grading, authentication, or persistent
student records. Case folding is JavaScript lowercase, not locale-specific.

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
Container: podman build -t p31 .; podman run --rm -p 127.0.0.1:8080:8080 p31
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (codex)
Version: 1.1.0.
Example: case-sensitive mismatch and missing response.
Input: {"cards":[{"id":"x","prompt":"Symbol?","answers":["Na"]},{"id":"y","prompt":"Word?","answers":["yes"]}],"responses":{"x":"na"},"caseSensitive":true}
Expected output: {"cardCount":2,"correct":0,"incorrect":1,"unanswered":1,"earnedPoints":0,"possiblePoints":2,"percent":0,"results":[{"id":"x","prompt":"Symbol?","status":"incorrect","response":"na","acceptedAnswers":["Na"],"earnedPoints":0,"possiblePoints":1},{"id":"y","prompt":"Word?","status":"unanswered","response":"","acceptedAnswers":["yes"],"earnedPoints":0,"possiblePoints":1}],"reviewIds":["x","y"]}
Supported limitation: Answer normalization does not provide fuzzy or semantic grading.
