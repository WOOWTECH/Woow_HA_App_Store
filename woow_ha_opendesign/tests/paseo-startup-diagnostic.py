#!/usr/bin/env python3
"""Add a CI-only, allowlisted error receipt to an ephemeral serve.mjs overlay."""

from pathlib import Path
import sys


target = Path(sys.argv[1])
source = target.read_text(encoding="utf-8")
needle = "}catch{\n if(!abort.signal.aborted){process.stderr.write('Paseo launcher initialization failed\\n');"
replacement = """}catch(error){
 if(!abort.signal.aborted){
  const safe=value=>typeof value==='string'&&/^[A-Za-z0-9_]{1,64}$/.test(value)?value:'UNKNOWN';
  const frames=String(error?.stack||'').split('\\n').map(line=>line.match(/(\\/opt\\/opendesign-paseo\\/[^:\\s)]+:\\d+:\\d+)/)?.[1]).filter(Boolean).slice(0,8);
  const status=Number.isInteger(error?.status)?error.status:null;
  process.stderr.write(`PASEO_DIAGNOSTIC ${JSON.stringify({name:safe(error?.name),code:safe(error?.code),status,frames})}\\n`);
  process.stderr.write('Paseo launcher initialization failed\\n');"""
if source.count(needle) != 1:
    raise SystemExit("diagnostic patch target missing or ambiguous")
target.write_text(source.replace(needle, replacement), encoding="utf-8")
