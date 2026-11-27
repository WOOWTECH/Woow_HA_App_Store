# Agent Connect 0.1.27 / Omnigent 0.3.42 pair — 2026-11-27

HA `0.15.28` pairs the Agent Connect `0.1.27` and Omnigent `0.3.42` GitHub
Release archives (`candidate-packages/manifest.json` records their
`releaseUrl`). Paseo runs `0.17.5-r4-8664f2c3f8f5` with the peer-matched a7
payload.

| Package | Source | Archive SHA-256 |
| --- | --- | --- |
| Agent Connect 0.1.27 | `053a39a7b72e83787a419b97206adc34f45e35bb` (source and archive build commit) | `aecf3bdff1505d3745ddc694f1e50fead50a0fc19b3fa2c82205174917143b6f` |
| Omnigent 0.3.42 | `7b56ad586711e6a707c6c3f36ff5dc5fef2790a4` | `7ffa8983e3bb2d9790f3122fd53db3e7adca4e24aed33f37aa4cc86bbeea5bb5` |

Agent Connect adapter SHA-256 is
`22d3a604d0c3ddc9305afe07f9f68524bec906fddb16636c08ac2783b4442a6c`.
Omnigent's combined adapter SHA-256 is
`8d55d6824307023eed5ead7fa89080650d3981fae1746378db9a400fab8a9632`;
its archive metadata binds Agent Connect `0.1.27` and removes the stale
`JSON3` dependency without changing its effective dependency set.

The sessions acceptance helper is part of the image smoke. It
checks a bounded raw gzip response and the ordinary `fetch().json()` path,
using only the image's loopback Pi Web process and owned synthetic sessions.
Its real local runtime receipt is
[`logs/sessions-http-json-live-piweb-receipt.json`](../logs/sessions-http-json-live-piweb-receipt.json):
Pi Web 0.12.0 launched via `node bin/pi-web.js`, installed Next 16.3.8,
with npm lock integrity and installed package hashes. This helper run is not
a Next 16.4.6 image test. Agent Connect's canonical production HTTP evidence
records Next.js 16.4.6 and valid gzip/JSON behavior in its build artifacts.

No HA image was built locally. HA image CI, Store comparison and
mock-Supervisor upgrade/startup checks gate publication.
