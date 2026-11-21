#!/bin/bash
# Install the Phase 1 rain-core unit on Raspberry Pi OS Lite 64-bit.
# This does not build an image and does not start Phase 2.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-run as root: sudo $0 $*" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AUTHORIZE_USER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --authorize-user)
      AUTHORIZE_USER="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: sudo $0 [--authorize-user NAME]" >&2
      exit 1
      ;;
  esac
done

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer expects apt-get (Raspberry Pi OS / Debian)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-yaml python3-pyudev python3-pip

if python3 -m pip install --help 2>/dev/null | grep -q break-system-packages; then
  python3 -m pip install --break-system-packages --no-deps "$ROOT"
else
  python3 -m pip install --no-deps "$ROOT"
fi

if ! getent group rain-core >/dev/null; then
  groupadd --system rain-core
fi
if ! getent passwd rain-core >/dev/null; then
  useradd --system --gid rain-core --home-dir /var/lib/rain --shell /usr/sbin/nologin rain-core
fi

install -d -o rain-core -g rain-core -m 0750 /var/lib/rain
install -d -o root -g root -m 0755 /usr/lib/rain /usr/lib/rain/modules /usr/lib/rain/devices /etc/rain
cp -a "$ROOT/share/modules/." /usr/lib/rain/modules/
cp -a "$ROOT/share/devices/rules.yaml" /usr/lib/rain/devices/rules.yaml
install -m 0644 "$ROOT/deploy/core.toml" /etc/rain/core.toml
install -m 0644 "$ROOT/deploy/rain-core.service" /etc/systemd/system/rain-core.service
install -d -m 0755 /etc/tmpfiles.d
install -m 0644 "$ROOT/deploy/tmpfiles.d/rain.conf" /etc/tmpfiles.d/rain.conf
install -m 0755 "$ROOT/deploy/rain-smoke.py" /usr/local/bin/rain-smoke

if [[ -n "$AUTHORIZE_USER" ]]; then
  if ! id "$AUTHORIZE_USER" >/dev/null 2>&1; then
    echo "No such user: $AUTHORIZE_USER" >&2
    exit 1
  fi
  SMOKE_UID="$(id -u "$AUTHORIZE_USER")"
  if [[ "$SMOKE_UID" -eq 0 ]]; then
    echo "Refusing to authorize uid 0." >&2
    exit 1
  fi
  CORE_UID="$(id -u rain-core)"
  if [[ "$SMOKE_UID" -eq "$CORE_UID" ]]; then
    echo "Refusing to authorize the rain-core account." >&2
    exit 1
  fi
  umask 022
  cat > /etc/rain/auth.toml <<EOF
[peers]
${SMOKE_UID} = "administrator"
EOF
  chmod 0644 /etc/rain/auth.toml
  usermod -aG rain-core "$AUTHORIZE_USER"
  echo "Authorized uid ${SMOKE_UID} (${AUTHORIZE_USER}) as administrator for this smoke test."
else
  install -m 0644 "$ROOT/deploy/auth.toml" /etc/rain/auth.toml
  echo "Installed the empty auth map. Assignment will be refused until a non-root uid is listed."
fi

if command -v systemd-tmpfiles >/dev/null 2>&1; then
  systemd-tmpfiles --create /etc/tmpfiles.d/rain.conf
fi
systemctl daemon-reload
systemctl enable --now rain-core
sleep 1
systemctl is-active rain-core
pid="$(systemctl show -p MainPID --value rain-core)"
echo "MainPID ${pid}"
ps -o uid=,user= -p "$pid"
awk '/^Uid:/ {print "effective", $3}' /proc/"$pid"/status
echo "rain-core account: $(id rain-core)"
echo
echo "Next, from a login of the authorized user (a new login if the group was just added):"
echo "  sg rain-core -c 'rain-smoke health'"
echo "Plug in one USB device that has a serial number, then:"
echo "  sg rain-core -c 'rain-smoke devices'"
echo "  sg rain-core -c 'rain-smoke assign dev_XXXXXXXXXXXXXXXX'"
echo "  sudo reboot"
echo "After reboot, confirm the assignment is still present, then:"
echo "  sudo systemctl disable --now rain-core"
echo "  sudo reboot"
echo "The second reboot must come up with rain-core inactive."
