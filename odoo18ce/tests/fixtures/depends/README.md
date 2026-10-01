# The `Depends` field of a pinned Odoo nightly

One file per `.deb`, named after the package and holding exactly what
`dpkg-deb -f odoo_<version>_all.deb Depends` prints — the input the bump bot's
merge (`.github/scripts/odoo_deb_depends.py`, issue #156) reads on a weekly
bump. `test_odoo_deb_depends.py` runs the merge against the newest file here
and the committed `odoo18ce/odoo-deb-depends.txt`, and that pair has to be a
no-op: the list already holds the normalizations the raw field does not.

The pair is matched by version. The list's `# source:` line names the `.deb` it
was generated from, and a file here must exist for it; when the bot bumps the
list past every file here the no-op test **skips** rather than fails — a red
static tier would cost the weekly bump pull request its image build, which is
the gate ADR 0002 rests on (ADR 0013, and `# source:`'s own note).

To add the current pin's field, read the control archive out of the first
2 MiB of the package rather than downloading all 235 MiB of it:

```sh
version=18.0.20260930
curl -fsS -r 0-2097151 \
  "https://nightly.odoo.com/18.0/nightly/deb/odoo_${version}_all.deb" -o head.bin
python3 - "$version" <<'PY'
import re, subprocess, sys
version = sys.argv[1]
data = open("head.bin", "rb").read()
assert data[:8] == b"!<arch>\n"
# `ar x` refuses a truncated archive; the member headers are 60 bytes each and
# parsing them by hand does not care that the data member is cut off.
at = 8
while at + 60 <= len(data):
    name = data[at:at + 16].decode().strip()
    size = int(data[at + 48:at + 58].decode().strip())
    if name.startswith("control.tar"):
        open(name, "wb").write(data[at + 60:at + 60 + size])
        subprocess.run("zstd -dc %s | tar -xO ./control > control" % name, shell=True, check=True)
        break
    at += 60 + size + size % 2
field = re.search(r"^Depends: (.*)$", open("control").read(), re.M).group(1)
open("odoo_%s_all.deb.Depends" % version, "w").write(field + "\n")
PY
```
