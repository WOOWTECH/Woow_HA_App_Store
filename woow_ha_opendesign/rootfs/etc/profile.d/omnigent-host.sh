# omnigent-host kit hook for the CLI Terminal login shell (ttyd does not descend
# from the kit launcher): puts the `omnigent` guard and omnigent-host-status
# first on PATH and prints the host status when the user has to act.
[ -r /etc/omnigent-host/omnigent-host-profile.sh ] && . /etc/omnigent-host/omnigent-host-profile.sh
:
