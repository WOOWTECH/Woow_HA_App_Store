#!/usr/bin/env python3
"""Add @openai: and @openai-api: prefixed model_routes to Hermes Gateway config.yaml.

Problem: WebUI sends model IDs like @openai:gpt-4o-mini (new sessions) or
@openai-api:gpt-4o-mini (old sessions) but Gateway's model_routes only have
bare keys (gpt-4o-mini), so _resolve_route() returns None and falls back to
default MiniMax-M1.

Fix: Add both @openai:* and @openai-api:* prefixed routes pointing to OpenRouter.

Usage (inside container):
  python3 /tmp/fix-model-routes.py [/opt/data/config.yaml]
"""
import os, sys

CONFIG = sys.argv[1] if len(sys.argv) > 1 else '/opt/data/config.yaml'
OPENROUTER_KEY = os.environ.get('OPENROUTER_API_KEY', '__OPENROUTER_API_KEY__')

# All OpenAI models visible in the WebUI picker
MODELS = [
    'gpt-5.5', 'gpt-5.5-pro', 'gpt-5.5-mini', 'gpt-5.4-mini', 'gpt-5.4',
    'gpt-5.4-nano', 'gpt-5-mini', 'gpt-5.3-codex', 'gpt-5.2-codex',
    'gpt-4.1', 'gpt-4o', 'gpt-4o-mini'
]

# ZhipuAI GLM models (bare name routes only, no @openai: prefix needed)
GLM_MODELS = [
    'glm-4.5', 'glm-4.5-flash', 'glm-4.7',
    'glm-5', 'glm-5-turbo', 'glm-5.1'
]

# Both prefixes: @openai: (new catalog IDs) and @openai-api: (old session IDs)
PREFIXES = ['@openai:', '@openai-api:']

with open(CONFIG, 'r') as f:
    content = f.read()

# Build YAML block for missing prefixes
route_lines = []
added = 0
for prefix in PREFIXES:
    if prefix in content:
        print(f"Skipping {prefix} routes (already exist)")
        continue
    for m in MODELS:
        route_lines.append(f'          "{prefix}{m}":')
        route_lines.append(f'            model: openai/{m}')
        route_lines.append(f'            base_url: https://openrouter.ai/api/v1')
        route_lines.append(f'            api_key: {OPENROUTER_KEY}')
        added += 1

# Add GLM bare-name routes
for m in GLM_MODELS:
    key = m
    if key not in content:
        route_lines.append(f'          "{key}":')
        route_lines.append(f'            model: z-ai/{m}')
        route_lines.append(f'            base_url: https://openrouter.ai/api/v1')
        route_lines.append(f'            api_key: {OPENROUTER_KEY}')
        added += 1

if added == 0:
    print("Already patched — both @openai: and @openai-api: routes exist")
    sys.exit(0)

insertion = '\n'.join(route_lines)

# Find the insertion point: after the last api_key: line inside model_routes.
#
# Comments are skipped. The generated config.yaml documents this very feature in a long comment
# block that contains both "model_routes:" and "# api_key:", so a naive substring scan decides
# there is a section when there is none - which is how a gateway with no provider configured used
# to end up reported as a corrupt config.
lines = content.split('\n')
insert_idx = None
in_model_routes = False

for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('#'):
        continue
    if 'model_routes:' in line:
        in_model_routes = True
    if in_model_routes and stripped.startswith('api_key:'):
        insert_idx = i

if insert_idx is None:
    # Nothing to do, not a failure. This script only ADDS routes to an existing routes block; with
    # no block, or a block with no configured route to anchor on, there is nowhere - and nothing -
    # to add. That is the ordinary state of a gateway that has not been given a provider yet, and
    # of every config.yaml adopted from the compose deployment.
    #
    # It matters because this script is the last command of woow-provision, which runs under
    # `set -euo pipefail`: a non-zero exit here fails hermes-provision.service and, through it,
    # scripts/install.sh and scripts/migrate-legacy.sh. The compose-era deploy.sh said the same
    # thing more bluntly, with `|| echo "(model routes: no model_routes section yet)"`.
    if not in_model_routes:
        print("No model_routes section yet: nothing to add "
              "(the gateway writes one once a provider is configured)")
    else:
        print("model_routes has no configured route to insert after: nothing to add")
    sys.exit(0)

lines.insert(insert_idx + 1, insertion)

with open(CONFIG, 'w') as f:
    f.write('\n'.join(lines))

print(f"Added {added} model routes ({added // len(MODELS)} prefixes x {len(MODELS)} models)")
