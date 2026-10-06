#!/usr/bin/env python3
"""Pi build preflight: an existing version is reused, never silently overwritten."""
import argparse,os
from addon_sync import GitHub,pi_image_reuse
p=argparse.ArgumentParser();p.add_argument('--arch',required=True);p.add_argument('--version',required=True);a=p.parse_args()
reuse=pi_image_reuse(GitHub(),os.environ['GITHUB_SHA'],a.arch,a.version)
print('Existing immutable runtime can be reused:',reuse)
with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('reuse='+str(reuse).lower()+'\n')
