#!/usr/bin/env bash
# prestop-top: the live, tabbed server view (server/top.py; q quits, ? lists the keys).
# Usage: sudo prestop-top [seconds between updates, default 2] [overview|system|services|traffic|data|learning|logs]
#        sudo prestop-top --once [tab]     print one frame and exit
exec python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/top.py" "$@"
