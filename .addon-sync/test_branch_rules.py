import copy,unittest
import addon_sync as s
import branch_rules as b

PROVIDER={'default_branch':'main','required_workflows':['.github/workflows/ci.yml'],'branch_rules':{'required_checks':['lint','build (amd64)'],'upgrade_comparison_pending':'#121'}}
WIRED=dict(PROVIDER,branch_rules={'required_checks':['lint','build (amd64)','Upgrade comparison / compare']})
def compliant():
    src={'ruleset_source_type':'Repository','ruleset_source':'WOOWTECH/test','ruleset_id':7}
    return [dict(src,type='deletion'),dict(src,type='non_fast_forward'),
        dict(src,type='pull_request',parameters={'required_approving_review_count':0,'require_code_owner_review':False}),
        dict(src,type='required_status_checks',parameters={'required_status_checks':[{'context':'lint'},{'context':'build (amd64)'},{'context':'extra'}]})]

class GH:
    """Answers the two public endpoints the check reads; `rulesets` stands in for the admin-only ruleset view."""
    def __init__(self,rules=None,default='main',rulesets=None):
        self.rules=compliant() if rules is None else rules;self.default=default;self.rulesets=rulesets
    def api(self,repo,path):
        if path=='':return {'default_branch':self.default,'archived':False}
        if path=='rules/branches/'+self.default:return self.rules
        if path.startswith('rulesets/'):
            if self.rulesets is None:raise s.Blocked('GitHub '+repo+'/'+path+' HTTP 404')
            return self.rulesets[int(path.split('/')[1])]
        raise AssertionError(path)

class Tests(unittest.TestCase):
    def test_compliant_repository_has_no_problems(self):
        self.assertEqual(b.check(GH(),None,'WOOWTECH/test',PROVIDER),[])
    def test_each_missing_rule_is_named(self):
        for kind in ['deletion','non_fast_forward','pull_request','required_status_checks']:
            with self.subTest(kind):
                rules=[r for r in compliant() if r['type']!=kind]
                problems=b.check(GH(rules),None,'WOOWTECH/test',PROVIDER)
                self.assertTrue(any(kind in p for p in problems),problems)
    def test_dropped_required_check_is_named(self):
        rules=compliant();rules[3]['parameters']['required_status_checks']=[{'context':'lint'}]
        self.assertEqual(b.check(GH(rules),None,'WOOWTECH/test',PROVIDER),['main: required check "build (amd64)" is not required'])
    def test_ruleset_without_the_upgrade_comparison_fails_the_wired_repository(self):
        # #89/#120: once a repository is wired, dropping the check from its ruleset is a problem even if the registry list loses it too.
        rules=compliant();rules[3]['parameters']['required_status_checks']=[{'context':'lint'},{'context':'build (amd64)'}]
        for name,provider in [('listed',WIRED),('not listed',dict(WIRED,branch_rules={'required_checks':['lint','build (amd64)']}))]:
            with self.subTest(name):
                self.assertEqual(b.check(GH(rules),None,'WOOWTECH/test',provider),['main: required check "Upgrade comparison / compare" is not required'])
    def test_repository_not_yet_wired_is_not_flagged(self):
        self.assertEqual(b.check(GH(),None,'WOOWTECH/test',PROVIDER),[])
    def test_run_names_the_wired_repository_that_lost_the_upgrade_comparison(self):
        registry={'providers':{'WOOWTECH/pending':PROVIDER,'WOOWTECH/wired':WIRED}}
        self.assertEqual(b.run(GH(),None,registry),{'WOOWTECH/pending':[],'WOOWTECH/wired':['main: required check "Upgrade comparison / compare" is not required']})
        rules=compliant();rules[3]['parameters']['required_status_checks'].append({'context':'Upgrade comparison / compare'})
        self.assertEqual(b.run(GH(rules),None,registry),{'WOOWTECH/pending':[],'WOOWTECH/wired':[]})
    def test_approval_or_code_owner_layer_is_not_the_standard(self):
        for key,value in [('required_approving_review_count',1),('require_code_owner_review',True)]:
            with self.subTest(key):
                rules=compliant();rules[2]['parameters'][key]=value
                self.assertEqual(len(b.check(GH(rules),None,'WOOWTECH/test',PROVIDER)),1)
    def test_default_branch_moved(self):
        problems=b.check(GH(default='dev'),None,'WOOWTECH/test',PROVIDER)
        self.assertEqual(problems,['default branch is dev, registry says main'])
    def test_bypass_actor_is_reported_with_an_admin_token(self):
        admin=GH(rulesets={7:{'id':7,'name':'main','bypass_actors':[{'actor_type':'RepositoryRole','actor_id':5,'bypass_mode':'always'}]}})
        self.assertEqual(b.check(GH(),admin,'WOOWTECH/test',PROVIDER),['main: ruleset "main" has bypass actors: RepositoryRole 5'])
        clean=GH(rulesets={7:{'id':7,'name':'main','bypass_actors':[]}})
        self.assertEqual(b.check(GH(),clean,'WOOWTECH/test',PROVIDER),[])
    def test_admin_token_that_cannot_see_bypass_is_a_problem(self):
        # GitHub omits bypass_actors for a token without Administration read.
        blind=GH(rulesets={7:{'id':7,'name':'main'}})
        self.assertEqual(b.check(GH(),blind,'WOOWTECH/test',PROVIDER),['main: ruleset "main": the token cannot read bypass_actors'])
    def test_run_skips_exempt_providers_and_reports_unreadable_ones(self):
        class Broken(GH):
            def api(self,repo,path):
                if repo=='WOOWTECH/gone':raise s.Blocked('GitHub WOOWTECH/gone/ HTTP 404')
                return super().api(repo,path)
        registry={'providers':{'WOOWTECH/test':PROVIDER,'WOOWTECH/gone':PROVIDER,
            'WOOWTECH/mirror':{'default_branch':'main','required_workflows':[],'branch_rules':{'exempt':'mirror'}}}}
        self.assertEqual(b.run(Broken(),None,registry),{'WOOWTECH/test':[],'WOOWTECH/gone':['GitHub WOOWTECH/gone/ HTTP 404']})
    def test_no_rules_at_all(self):
        self.assertEqual(len(b.check(GH([]),None,'WOOWTECH/test',PROVIDER)),4)

if __name__=='__main__':unittest.main()
