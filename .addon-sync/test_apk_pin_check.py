"""Tests for the shared base-image resolution (addon_build, #228)."""
import json,os,pathlib,shutil,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
import addon_build as b

class Addon(unittest.TestCase):
    def addon(self,files,config=None):
        d=pathlib.Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,d)
        files={'config.yaml':json.dumps(config or {'slug':'t','version':'1.0.0','arch':['amd64','aarch64']}),**files}
        for name,text in files.items():
            p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        return d

class BaseImage(Addon):
    """addon_build.base_image: build_from, else the Dockerfile's BUILD_FROM default, else the FROM written out."""
    def test_build_from_wins_over_the_dockerfile_default(self):
        d=self.addon({'build.yaml':'build_from:\n  amd64: a/amd64:1\n  aarch64: a/aarch64:1\n','Dockerfile':'ARG BUILD_FROM=x/y:9\nFROM ${BUILD_FROM}\n'})
        self.assertEqual(b.base_image(d,'amd64')[1],'a/amd64:1');self.assertEqual(b.base_image(d,'aarch64')[1],'a/aarch64:1')
    def test_without_a_build_file_the_build_from_default_counts(self):
        # Current Supervisor passes BUILD_FROM only with a build file (supervisor/apps/build.py).
        d=self.addon({'Dockerfile':'ARG BUILD_FROM=ghcr.io/hassio-addons/base:21.0.2\nFROM ${BUILD_FROM}\n'})
        self.assertEqual(b.base_image(d,'aarch64')[1],'ghcr.io/hassio-addons/base:21.0.2')
    def test_a_written_from_and_build_arch(self):
        d=self.addon({'Dockerfile':'ARG BUILD_ARCH\nARG TAG="bookworm-1"\nFROM ghcr.io/home-assistant/${BUILD_ARCH}-base-debian:${TAG}\n'})
        self.assertEqual(b.base_image(d,'aarch64')[1],'ghcr.io/home-assistant/aarch64-base-debian:bookworm-1')
    def test_the_last_stage_and_the_stages_it_starts_from(self):
        d=self.addon({'Dockerfile':'FROM node:22-alpine AS ui\nRUN true\nFROM a/b:1 AS base\nFROM base AS final\n'})
        _,image,chain,stages,_=b.base_image(d,'amd64')
        self.assertEqual(image,'a/b:1');self.assertEqual(chain,[1,2]);self.assertEqual(stages[0]['image'],'node:22-alpine')
    def test_an_unresolved_from_is_an_error(self):
        with self.assertRaisesRegex(ValueError,r'\$NOPE has no value'):b.base_image(self.addon({'Dockerfile':'FROM ${NOPE}\n'}),'amd64')
    def test_build_args_is_the_same_function_upgrade_check_uses(self):
        import upgrade_check
        self.assertIs(upgrade_check.build_args,b.build_args)


if __name__=='__main__':unittest.main()
