#!/usr/bin/env python3
"""Daily check that every gated source repository still has its branch rules.

ADR-0005 in the pipeline workspace: a release is a merged version-bump PR that
passed the required checks, so each non-exempt registry provider's default
branch must keep a ruleset with a PR requirement, the registry's required
checks, and no deletion or force push. The shared WOOWTECH account can change
those rules; this check makes a change visible. Exempt providers (mirrors, the
upstream fork, retired sources) carry `branch_rules.exempt` with the reason.
"""
from __future__ import annotations
import argparse, json, os, pathlib, sys
from addon_sync import Blocked, GitHub, markdown_cell, workflow_command

REQUIRED_RULES = ['pull_request', 'required_status_checks', 'deletion', 'non_fast_forward']
# Pipeline #89: the caller job `Upgrade comparison` of woow-addon-upgrade-check.yml (inner job `compare`).
# Every gated provider requires it, except one still being wired, which carries
# branch_rules.upgrade_comparison_pending with the ticket that wires it.
UPGRADE_CHECK = 'Upgrade comparison / compare'

def expected_checks(provider):
    """Check names the provider's ruleset must require: the registry's list, plus the upgrade comparison unless pending."""
    rules=provider['branch_rules'];names=list(rules['required_checks'])
    if 'upgrade_comparison_pending' not in rules and UPGRADE_CHECK not in names:names.append(UPGRADE_CHECK)
    return names

def check(gh, admin_gh, repo, provider):
    """Problems with `repo`'s default-branch rules, as messages; empty when it meets the standard."""
    problems=[]
    branch=provider['default_branch']
    actual=gh.api(repo,'')['default_branch']
    # Rules on the registry's branch say nothing about the branch that actually ships.
    if actual!=branch:return [f'default branch is {actual}, registry says {branch}']
    # Only active rulesets appear here; evaluate-mode and disabled ones do not protect anything.
    rules=gh.api(repo,'rules/branches/'+branch)
    kinds={r['type'] for r in rules}
    for kind in REQUIRED_RULES:
        if kind not in kinds:problems.append(f'{branch}: no active {kind} rule')
    for r in rules:
        p=r.get('parameters') or {}
        if r['type']=='pull_request':
            # ADR-0005: the checks are the approval; no reviewer or CODEOWNERS layer.
            if p.get('required_approving_review_count',0)!=0:problems.append(f'{branch}: pull_request requires {p["required_approving_review_count"]} approvals, the standard is 0')
            if p.get('require_code_owner_review'):problems.append(f'{branch}: pull_request requires CODEOWNERS review, the standard has none')
    required={c['context'] for r in rules if r['type']=='required_status_checks' for c in r['parameters']['required_status_checks']}
    if 'required_status_checks' in kinds:
        for name in expected_checks(provider):
            if name not in required:problems.append(f'{branch}: required check "{name}" is not required')
    # bypass_actors is only visible to a token with Administration read; without one the caller warns instead.
    if admin_gh is not None:
        for ruleset_id in sorted({r['ruleset_id'] for r in rules if r.get('ruleset_source_type')=='Repository'}):
            try:ruleset=admin_gh.api(repo,f'rulesets/{ruleset_id}')
            except Blocked as e:problems.append(f'{branch}: ruleset {ruleset_id}: {e}');continue
            if 'bypass_actors' not in ruleset:problems.append(f'{branch}: ruleset "{ruleset["name"]}": the token cannot read bypass_actors');continue
            if ruleset['bypass_actors']:
                actors=', '.join(f'{a["actor_type"]} {a.get("actor_id")}' for a in ruleset['bypass_actors'])
                problems.append(f'{branch}: ruleset "{ruleset["name"]}" has bypass actors: {actors}')
    return problems

def run(gh, admin_gh, registry):
    """{repo: problems} for every gated provider; exempt providers are skipped."""
    report={}
    for repo,provider in registry['providers'].items():
        if 'exempt' in provider['branch_rules']:continue
        try:report[repo]=check(gh,admin_gh,repo,provider)
        except Blocked as e:report[repo]=[str(e)]
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);p.add_argument('--registry',default='.addon-sync/registry.json');p.add_argument('--result')
    a=p.parse_args();registry=json.loads(pathlib.Path(a.registry).read_text(encoding='utf-8'))
    admin_token=os.environ.get('BRANCH_RULES_TOKEN','')
    report=run(GitHub(),GitHub(admin_token) if admin_token else None,registry)
    lines=['## Source branch rules','','| Repository | Result |','|---|---|']
    for repo,problems in report.items():
        lines.append(f'| {repo} | '+('OK' if not problems else markdown_cell('<br>'.join(problems)))+' |')
        for problem in problems:print(workflow_command('error',repo,problem))
    if not admin_token:
        print('::warning title=Bypass not checked::BRANCH_RULES_TOKEN is not set, so bypass_actors were not checked (GitHub shows them only to a token with Administration read).')
        lines+=['','Bypass actors not checked: BRANCH_RULES_TOKEN is not set.']
    text='\n'.join(lines)+'\n';print(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:f.write(text)
    if a.result:pathlib.Path(a.result).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if any(report.values()):sys.exit(1)

if __name__=='__main__':main()
