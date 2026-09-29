#!/usr/bin/env python3
"""Static-tier contracts for the slow-link pull script's image resolution (#157).

The script downloads a Release image from ghcr and loads it, so the first
thing it has to know is *which* image. It used to ask the Supervisor and
nothing else — and on Supervisor 2026.09.2 that answer is gone: `.data.image`
is absent from `ha apps info`, `ha addons info` and the REST
`/addons/<slug>/info` and `/store/addons/<slug>` alike, measured on the test
host on 2026-09-28. The script died at its first step on every current host.

Resolution is now three sources in order — the Supervisor, the installed
add-on container, `--image` — and these tests drive the real script with
stubs for `ha`, `docker` and `curl` on PATH. `curl` refuses, so every run
stops at the token request (exit 5) having already logged the image it
resolved; that log line is what the assertions read.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import require_bash

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT.parent / "docs/runbooks/slow-link-pull.sh"

SLUG = "1b7b4ce7_odoo18ce"
IMAGE = "ghcr.io/woowtech/woow-ha-odoo-amd64"
EXIT_USAGE = 2
EXIT_SUPERVISOR = 4
EXIT_TOKEN = 5

# What `ha info --raw-json` answers. The arch is what `{arch}` resolves to.
HA_INFO = '{"result":"ok","data":{"arch":"amd64"}}'


def app_json(image: str | None) -> str:
    """`ha apps info --raw-json`, with or without the field Supervisor dropped."""
    fields = '"version":"0.4.4","version_latest":"0.4.4","build":false'
    if image is not None:
        fields += f',"image":"{image}"'
    return '{"result":"ok","data":{' + fields + "}}"


def write_stubs(
    tmp_path: Path,
    *,
    app: str | None,
    containers: dict[str, str],
    with_docker: bool = True,
) -> Path:
    """A PATH directory holding `ha`, `docker` and a `curl` that refuses.

    `app=None` is a host where the add-on was never installed: `ha apps info`
    fails there, which is the state `--image` has to survive.
    """
    bind = tmp_path / "bin"
    bind.mkdir()

    app_arm = f"  \"apps info\") printf '%s' {app!r} ;;\n" if app is not None else ""
    ha = bind / "ha"
    ha.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1 $2" in\n'
        f'  "info --raw-json") printf \'%s\' {HA_INFO!r} ;;\n'
        f"{app_arm}"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )

    # `docker inspect --format '{{.Config.Image}}' <name>` and nothing else.
    cases = "".join(
        f'  "{name}") printf \'%s\\n\' "{image}" ;;\n'
        for name, image in containers.items()
    )
    docker = bind / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$1" = "inspect" ] || exit 1\n'
        'case "${!#}" in\n' + cases + "  *) exit 1 ;;\nesac\n",
        encoding="utf-8",
    )

    # No network in the Static tier. A curl that refuses stops the script at
    # the token request, which is after the image is resolved and logged.
    curl = bind / "curl"
    curl.write_text("#!/usr/bin/env bash\nexit 7\n", encoding="utf-8")

    written = [ha, curl]
    if with_docker:
        written.append(docker)
    else:
        docker.unlink()
        # A PATH with no docker at all still needs what the script checks for
        # before it looks for one, so those come along as symlinks.
        for tool in ("env", "bash", "jq", "sha256sum", "tar", "date", "sed", "mkdir"):
            found = shutil.which(tool)
            if found:
                (bind / tool).symlink_to(found)
    for f in written:
        f.chmod(0o755)
    return bind


def run(
    tmp_path: Path,
    *args: str,
    app: str | None,
    containers: dict[str, str],
    with_docker: bool = True,
):
    bash = require_bash()
    bind = write_stubs(
        tmp_path, app=app, containers=containers, with_docker=with_docker
    )
    env = dict(os.environ)
    if with_docker:
        env["PATH"] = f"{bind}{os.pathsep}{env['PATH']}"
    else:
        # Isolated: the point of the case is that `command -v docker` fails.
        env["PATH"] = str(bind)
    env["SLOW_LINK_WORK_ROOT"] = str(tmp_path / "work")
    return subprocess.run(
        [bash, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_supervisor_answer_is_used_when_it_still_carries_one(tmp_path):
    """A Supervisor that answers with the image is still believed first."""
    proc = run(
        tmp_path,
        SLUG,
        app=app_json("ghcr.io/woowtech/woow-ha-odoo-{arch}"),
        containers={},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert proc.returncode == EXIT_TOKEN


def test_the_installed_container_answers_when_the_supervisor_does_not(tmp_path):
    """Supervisor 2026.09's payload, and the container the add-on runs."""
    proc = run(
        tmp_path,
        SLUG,
        app=app_json(None),
        containers={f"app_{SLUG}": f"{IMAGE}:0.4.4"},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert proc.returncode == EXIT_TOKEN


def test_the_older_container_prefix_is_read_too(tmp_path):
    """`addon_` was the prefix before `app_`; a host may still run one."""
    proc = run(
        tmp_path,
        SLUG,
        app=app_json(None),
        containers={f"addon_{SLUG}": f"{IMAGE}:0.4.2"},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert proc.returncode == EXIT_TOKEN


def test_the_container_tag_is_not_the_version_asked_for(tmp_path):
    """The container names the *old* tag — only its repository is taken."""
    proc = run(
        tmp_path,
        SLUG,
        "0.4.4",
        app=app_json(None),
        containers={f"app_{SLUG}": f"{IMAGE}:0.4.2"},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert f"{IMAGE}:0.4.2" not in proc.stdout


def test_the_image_option_wins_and_loses_its_tag(tmp_path):
    """`--image` is the third source and overrides both."""
    proc = run(
        tmp_path,
        "--image",
        f"{IMAGE}:0.4.2",
        SLUG,
        "0.4.4",
        app=app_json("ghcr.io/woowtech/something-else"),
        containers={f"app_{SLUG}": "ghcr.io/woowtech/another:0.1.0"},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert "something-else" not in proc.stdout


def test_no_source_names_all_three(tmp_path):
    """Nothing to read anywhere: refuse, and say where it looked."""
    proc = run(tmp_path, SLUG, app=app_json(None), containers={})
    assert proc.returncode == EXIT_SUPERVISOR
    assert ".data.image" in proc.stderr
    assert f"app_{SLUG}" in proc.stderr
    assert "--image" in proc.stderr


def test_an_image_off_ghcr_is_refused(tmp_path):
    """The script's scope of access is ghcr and the redirect it returns."""
    proc = run(
        tmp_path,
        "--image",
        "docker.io/library/alpine",
        SLUG,
        app=app_json(None),
        containers={},
    )
    assert proc.returncode == EXIT_SUPERVISOR
    assert "is not on ghcr.io" in proc.stderr


@pytest.mark.parametrize(
    "given,expected",
    [
        ("ghcr.io/woowtech/img:0.4.4", "ghcr.io/woowtech/img"),
        ("ghcr.io/woowtech/img", "ghcr.io/woowtech/img"),
        ("ghcr.io/woowtech/img@sha256:" + "0" * 64, "ghcr.io/woowtech/img"),
    ],
)
def test_a_reference_loses_only_its_tag_or_digest(tmp_path, given, expected):
    """A tag and a digest come off; the repository path does not."""
    proc = run(
        tmp_path,
        "--image",
        given,
        SLUG,
        "0.4.4",
        app=app_json(None),
        containers={},
    )
    assert f"image  {expected}:0.4.4" in proc.stdout


def test_a_registry_with_a_port_is_not_this_registry(tmp_path):
    """`ghcr.io:443/...` is a different host to the gate, and is refused.

    `strip_tag` keeps the port — only the last path segment can carry a tag —
    so what refuses this is the scope-of-access check and not a mangled
    reference. Recorded because the two are easy to confuse when reading the
    error.
    """
    proc = run(
        tmp_path,
        "--image",
        "ghcr.io:443/woowtech/img:0.4.4",
        SLUG,
        "0.4.4",
        app=app_json(None),
        containers={},
    )
    assert proc.returncode == EXIT_SUPERVISOR
    assert "ghcr.io:443/woowtech/img is not on ghcr.io" in proc.stderr


# ---------------------------------------------------------------------------
# The four findings of the 2026-09-28 review of this change, each as the case
# that would have caught it.


def test_the_image_option_survives_a_host_that_never_installed_the_addon(tmp_path):
    """`ha apps info` fails there, and asking for it anyway would exit 4.

    With both `--image` and a version on the command line the add-on's record
    answers nothing, so it is not asked for at all.
    """
    proc = run(
        tmp_path,
        "--image",
        IMAGE,
        SLUG,
        "0.4.4",
        app=None,
        containers={},
    )
    assert f"image  {IMAGE}:0.4.4" in proc.stdout
    assert proc.returncode == EXIT_TOKEN


def test_the_image_option_without_a_version_still_asks_the_supervisor(tmp_path):
    """The version has to come from somewhere, and that is the honest error."""
    proc = run(tmp_path, "--image", IMAGE, SLUG, app=None, containers={})
    assert proc.returncode == EXIT_SUPERVISOR
    assert "ha apps info" in proc.stderr


def test_a_host_without_docker_is_told_that_and_not_something_else(tmp_path):
    """The dry run needs no docker, but reading the container does.

    The official SSH add-on has no docker, and the message has to name that
    rather than claim the container is missing.
    """
    proc = run(
        tmp_path,
        "--dry-run",
        SLUG,
        app=app_json(None),
        containers={},
        with_docker=False,
    )
    assert proc.returncode == EXIT_SUPERVISOR
    assert "docker is not on PATH" in proc.stderr
    assert "--image" in proc.stderr


def test_a_container_made_from_an_image_id_is_not_mangled(tmp_path):
    """`docker inspect` answers with an ID when there is no name to answer.

    Stripping a tag off `sha256:<hex>` would leave the string `sha256` and an
    error about a foreign registry.
    """
    proc = run(
        tmp_path,
        SLUG,
        app=app_json(None),
        containers={f"app_{SLUG}": "sha256:" + "a" * 64},
    )
    assert proc.returncode == EXIT_SUPERVISOR
    assert "image ID" in proc.stderr
    assert "--image" in proc.stderr
    assert "sha256 is not on" not in proc.stderr


@pytest.mark.parametrize("args", [("--image", ""), ("--image=",)])
def test_an_empty_image_value_is_refused(tmp_path, args):
    """Silently falling back would spend hours downloading the wrong thing."""
    proc = run(tmp_path, *args, SLUG, app=app_json(None), containers={})
    assert proc.returncode == EXIT_USAGE
    assert "empty value" in proc.stderr


def test_the_image_option_does_not_swallow_the_next_option(tmp_path):
    """`--image --dry-run <slug>` means the dry run silently did not happen."""
    proc = run(
        tmp_path,
        "--image",
        "--dry-run",
        SLUG,
        app=app_json(None),
        containers={},
    )
    assert proc.returncode == EXIT_USAGE
    assert "--dry-run" in proc.stderr
