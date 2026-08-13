# Smoke tests

Two scripts, kept independent so you can run whichever part you care about.

## `smoke-providers.sh` — do the API keys actually work?

Hits the two upstream providers with a tiny completion request. Catches out-of-balance / revoked / wrong-region keys **before** a user tries to chat in pi-web and gets an opaque 401 / 429.

```bash
GLM_API_KEY=...  MINIMAX_API_KEY=...  ./tests/smoke-providers.sh
```

- `GLM_API_KEY` is required.
- `MINIMAX_API_KEY` is optional — the MiniMax check is skipped if unset (matches the add-on's behaviour).
- MiniMax check also asserts `<think>…</think>` shows up inline in the response, which is what `thinkingFormat: "deepseek"` in `models.json` relies on to surface reasoning tokens.

## `smoke-addon.sh` — is the deployed add-on healthy?

Talks to a live HA Supervisor via a long-lived token. Verifies four things:

1. Supervisor reports the add-on `installed` + `state=started` + no update pending.
2. Log tail contains the bootstrap lines proving `models.json` was seeded (GLM required, MiniMax optional).
3. Ingress `"/"` returns HTML with `/_next/…` paths rewritten to include the ingress prefix — this is the nginx sub_filter proving it works.

```bash
HA_URL=https://your-ha.example.com \
HA_TOKEN=eyJ...  \
ADDON_SLUG=b9cf5676_woow_ha_pi_agent \
./tests/smoke-addon.sh
```

Long-lived token: HA UI → your user profile → **Long-lived access tokens** → **Create token**.
