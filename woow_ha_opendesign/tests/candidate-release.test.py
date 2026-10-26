#!/usr/bin/env python3
import importlib.util
import io
import json
from pathlib import Path
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('candidate', Path(__file__).resolve().parents[1] / '.github/scripts/candidate-release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CONFIG = 'version: "0.2.8"\n'
ENV = dict(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/review',
           GITHUB_REPOSITORY='WOOWTECH/Woow_ha_opendesign_add_on', GITHUB_RUN_ID='123',
           GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40,
           CANDIDATE_CORE_IMAGE='ghcr.io/woowtech/open-design-core:20261026.0654@sha256:'+'b'*64)

class CandidateTests(unittest.TestCase):
    def test_unique_candidate_in_existing_public_repository(self):
        value=module.plan(ENV,CONFIG)
        self.assertEqual(value['image'],'ghcr.io/woowtech/woow-ha-opendesign-amd64:0.2.8-rc.123.1')
        self.assertEqual(value['core'],ENV['CANDIDATE_CORE_IMAGE'])
        core='jcr-prod.woowtech.io/woow-paas-docker-local/open-design-core:20261026.0642-pending-approval@sha256:'+'b'*64
        self.assertEqual(module.plan({**ENV,'CANDIDATE_CORE_IMAGE':core},CONFIG)['core'],core)
    def test_rejects_other_publication_scopes(self):
        for key,values in {'GITHUB_EVENT_NAME':['push','pull_request'], 'GITHUB_REF':['refs/heads/main','refs/tags/v0.2.8',''],
                           'GITHUB_REPOSITORY':['fork/addon'], 'GITHUB_RUN_ID':['0','../main','1\nX=y'],
                           'GITHUB_RUN_ATTEMPT':['-1',''], 'GITHUB_SHA':['a'*39]}.items():
            for value in values:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):module.plan({**ENV,key:value},CONFIG)
    def test_rejects_mutable_foreign_or_injected_core(self):
        good=ENV['CANDIDATE_CORE_IMAGE']
        for core in [good.split('@')[0],good.replace('open-design-core','other'),good+'\nBAD=1',good.replace('b'*64,'0'*64),good.replace('ghcr.io','example.org'),good+';touch /tmp/pwned']:
            with self.subTest(core=core),self.assertRaises(ValueError):module.plan({**ENV,'CANDIDATE_CORE_IMAGE':core},CONFIG)
    def test_registry_only_404_is_absent(self):
        for status in [401,403,404,429,500]:
            def opener(request,**kwargs):
                if '/token?' in request.full_url:return io.BytesIO(b'{"token":"fixture"}')
                raise urllib.error.HTTPError(request.full_url,status,'fixture',{},None)
            if status==404:self.assertIsNone(module.manifest('0.2.8-rc.123.1',opener=opener))
            else:
                with self.assertRaises(ValueError):module.manifest('0.2.8-rc.123.1',opener=opener)
    def test_manifest_integrity_and_stable_tag_rejection(self):
        raw=b'{"schemaVersion":2}'
        digest='sha256:'+module.hashlib.sha256(raw).hexdigest()
        def opener(request,**kwargs):
            if '/token?' in request.full_url:return io.BytesIO(b'{"token":"fixture"}')
            body=io.BytesIO(raw);body.headers={'Docker-Content-Digest':digest};return body
        self.assertEqual(module.manifest('0.2.8-rc.123.1',opener=opener),digest)
        for tag in ['0.2.8','stable','0.2.8-rc.1.0']:
            with self.assertRaises(ValueError):module.manifest(tag,opener=opener)
        digest='sha256:'+'0'*64
        with self.assertRaises(ValueError):module.manifest('0.2.8-rc.123.1',opener=opener)

if __name__=='__main__':unittest.main()
