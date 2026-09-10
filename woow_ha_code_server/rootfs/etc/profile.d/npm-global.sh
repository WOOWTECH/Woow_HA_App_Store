# Put the npm global prefixes back on PATH for login shells.
#
# /etc/profile overwrites PATH wholesale for every login shell, discarding
# whatever the image ENV set. code-server's integrated terminal IS a login
# shell, so without this a package the user installed with
# `npm install -g <pkg>` would install successfully and then be
# "command not found" in the very terminal they installed it from.
#
# pi itself deliberately does NOT rely on this: it is installed at image
# build time through a prefix whose bin dir survives /etc/profile's reset
# on its own, so `pi` resolves identically in login and non-login shells.
# See the npm prefix block in the image build for why that ordering matters.
#
# Both entries are guarded on existence because the two prefixes differ per
# deployment: the runtime prefix is only created where the run user is not
# root, and the persistent one only exists once the state volume is seeded.
#
# - runtime prefix: writable by the run user, lives in the container's
#   writable layer, lost on recreate — same as VS Code extensions.
# - persistent prefix on the pi state volume: opt-in, for globals that
#   should survive a recreate:
#       npm install -g --prefix /data/pi-agent/npm-global <pkg>
for _npm_bin in /opt/npm-global/bin "${PI_AGENT_DATA_DIR:-/data/pi-agent}/npm-global/bin"; do
    [ -d "${_npm_bin}" ] || continue
    case ":${PATH}:" in
        *":${_npm_bin}:"*) ;;
        *) PATH="${_npm_bin}:${PATH}" ;;
    esac
done
unset _npm_bin
export PATH
