Text Keyword Frequencies
========================

Counts normalized words and contiguous two/three-word phrases. Filters stop
words and short tokens and returns deterministic rankings and percentages.

Fields
- text (required string, at most 200000 characters).
- stopWords (optional array, at most 2000; default []): each must be a single
  token, 1–100 characters. Uses the same normalization as the source text.
- caseSensitive (optional boolean, default false).
- minLength (optional integer, 1–50, default 1): Unicode code points per token.
- ngramSize (optional integer, 1–3, default 1).
- top (optional integer, 1–100, default 10).

Behavior
Applies NFKC normalization, converts curly apostrophes to straight apostrophes,
and normally lowercases text. Tokens contain Unicode letters/numbers with
internal apostrophes. Punctuation separates words. Phrase windows are built
from the original token sequence and skipped when ANY token is a stop word
or too short; excluded tokens are never bridged to invent new phrases.
totalTokens is before filtering. matchedTerms is the number of accepted windows;
uniqueTerms is the number of distinct accepted terms. Rankings sort by count
descending then lexical term order. Percentages use all matched terms, even
when top truncates the list, and round to six decimals. Empty results are valid.

Limits
At most 30000 tokens. No stemming, language detection, sentence boundary logic
or linguistic CJK segmentation. Phrases may cross punctuation/sentences. Adjacent
CJK characters form one token. Percentages can sum slightly differently from
100 due to rounding or top truncation.

Worked example (manually specified fixture)
Input:
{
  "text": "Blue sky, blue sea. Sky!",
  "stopWords": []
}

Expected result:
{
  "totalTokens": 5,
  "matchedTerms": 5,
  "uniqueTerms": 3,
  "frequencies": [
    {
      "term": "blue",
      "count": 2,
      "percent": 40
    },
    {
      "term": "sky",
      "count": 2,
      "percent": 40
    },
    {
      "term": "sea",
      "count": 1,
      "percent": 20
    }
  ]
}

Run locally (Node.js standard library only; no install or network needed)
  node test.mjs
  node --input-type=module -e "import {meta,run} from './app.mjs'; console.log(JSON.stringify(run(meta.example),null,2))"

To pass your own JSON on stdin:
  node --input-type=module -e "import {readFileSync} from 'node:fs'; import {run} from './app.mjs'; console.log(JSON.stringify(run(JSON.parse(readFileSync(0,'utf8'))),null,2))"

Integration
app.mjs exports meta and a synchronous run(input). The coordinator owns the
shared interactive page, runtime.mjs, main.mjs and package.json. This batch does
not create or change the shared server, deployment, packages or platform.

Shared safeguards
Input must be a JSON object with finite numbers and no cycles, at most 30000
JSON nodes, 32 levels of nesting, 1000000 total key/string characters, and no
individual string over 200000 characters. These shared bounds also apply when
per-field counts would otherwise permit larger data. Bad configuration/input
throws Error with a useful message. All examples are synthetic. No credentials,
external dependencies, network access, eval or production certification claims.

Tests
11 independent cases in cases.json, including correct outputs and useful
rejections. test.mjs also checks example execution, repeatability, JSON-safe
outputs, input immutability, cycles, nonfinite values, oversize strings and depth.

Standalone run (Node.js 22+): npm test; npm start
PORT=18750 BIND=127.0.0.1 defaults. No npm install needed.
Input is JSON; Run calculates; Save persists browser input; export downloads result.
Container: podman build -t p09 .; podman run --rm -p 127.0.0.1:8080:8080 p09
Source download is supplied by the multi-project portal.

Omnigent lifecycle review (claude)
==================================
Version 1.1.0 (bumped from 1.0.0 in this review).
Example (meta.example, observed output from run):
  input:  {"text":"Blue sky, blue sea. Sky!","stopWords":[],"ngramSize":1,"top":10}
  output: {"totalTokens":5,"matchedTerms":5,"uniqueTerms":3,"frequencies":[{"term":"blue","count":2,"percent":40},{"term":"sky","count":2,"percent":40},{"term":"sea","count":1,"percent":20}]}
Supported limitation: No stemming or CJK segmentation; phrases may cross punctuation; at most 30000 tokens.
