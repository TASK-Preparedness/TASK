# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. installer guard library (sourced by preflight.sh / install.sh / rollback.sh). Bash only.
# Rules: absolute tool paths, argv arrays, no eval, no shell interpolation of package data, never autoremove,
# never remove/purge, never apt-mark, never start/enable services, never touch config outside $HOME backups.
#
# NO OVERRIDES: tool paths and /etc/os-release are fixed. There is no test mode, no environment variable and
# no file marker that changes behaviour. Tests run these exact scripts inside a private user+mount namespace with
# fixture files bind-mounted over /usr/bin/* and /etc/os-release (release/common/tests/test_installers.py).
# The entry scripts also re-run themselves in a whitelisted environment under `bash -p` (see tg_prologue in
# preflight.sh / install.sh / rollback.sh), so BASH_ENV, LD_PRELOAD, APT_CONFIG, PATH, etc. never reach a check.

APT_GET=/usr/bin/apt-get; APT_MARK=/usr/bin/apt-mark; DPKG=/usr/bin/dpkg; DPKGQ=/usr/bin/dpkg-query
DPKG_DEB=/usr/bin/dpkg-deb; SUDO=/usr/bin/sudo; ID=/usr/bin/id; PGREP=/usr/bin/pgrep
readonly OS_RELEASE=/etc/os-release TG_REQ_ARCH=arm64 TG_REQ_ID=debian TG_REQ_VERSION_ID=13 TG_REQ_CODENAME=trixie
TG_FAIL=0
TG_WARN=0
tg_say()  { printf '%s\n' "$*"; }
tg_ok()   { printf '  OK    %s\n' "$*"; }
tg_warn() { printf '  WARN  %s\n' "$*"; TG_WARN=$((TG_WARN + 1)); }
tg_fail() { printf '  FAIL  %s\n' "$*"; TG_FAIL=$((TG_FAIL + 1)); }
tg_ver()  { "$DPKGQ" -W -f='${Status} ${Version}\n' "$1" 2>/dev/null | /usr/bin/awk '$3=="installed"{print $4}'; }
tg_lt()   { "$DPKG" --compare-versions "$1" lt "$2"; }
tg_gt()   { "$DPKG" --compare-versions "$1" gt "$2"; }

tg_not_root() {
    if [ "$("$ID" -u)" = "0" ]; then tg_say "Run as the desktop user, not root (sudo is asked for only the apt step)."; exit 2; fi
}

# ---------------------------------------------------------------------------------------------------------
# HOST PLATFORM (hard requirement, shared by preflight.sh, install.sh and rollback.sh)
# Accepted: `dpkg --print-architecture` = arm64 AND /etc/os-release with ID=debian, VERSION_ID=13,
# VERSION_CODENAME=trixie. That is what Debian 13 arm64 and 64-bit Raspberry Pi OS (trixie) report.
# 32-bit Raspberry Pi OS reports ID=raspbian (armhf) and is rejected; ID_LIKE is deliberately NOT used as
# a fallback, because Ubuntu and other derivatives also declare ID_LIKE=debian.
# os-release is PARSED, never sourced: only blank lines, comments, and KEY=VALUE lines (unquoted safe chars,
# or a "double" / 'single' quoted string) are allowed; duplicate keys, other lines or a file > 64 KiB are
# rejected as malformed.
TG_OSR_ID=""; TG_OSR_VERSION_ID=""; TG_OSR_CODENAME=""; TG_OSR_ERR=""
tg_parse_os_release() {
    local f="$1" line n=0 key val seen=" "
    TG_OSR_ID=""; TG_OSR_VERSION_ID=""; TG_OSR_CODENAME=""; TG_OSR_ERR=""
    if [[ ! -e "$f" ]]; then TG_OSR_ERR="$f does not exist"; return 1; fi
    if [[ ! -f "$f" || ! -r "$f" ]]; then TG_OSR_ERR="$f is not a readable regular file"; return 1; fi
    if [[ "$(/usr/bin/stat -L -c %s -- "$f" 2>/dev/null)" -gt 65536 ]]; then TG_OSR_ERR="$f is larger than 64 KiB"; return 1; fi
    while IFS= read -r line || [[ -n "$line" ]]; do
        n=$((n + 1))
        [[ "$line" =~ ^[[:space:]]*$ || "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)=(\"([^\"\\\$\`]|\\.)*\"|\'[^\']*\'|[A-Za-z0-9._:/+@%-]*)$ ]]; then
            key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
        else
            TG_OSR_ERR="$f line $n is not a valid KEY=VALUE line: '${line:0:80}'"; return 1
        fi
        if [[ "$seen" == *" $key "* ]]; then TG_OSR_ERR="$f line $n: duplicate key $key"; return 1; fi
        seen="$seen$key "
        if [[ "$val" == \"*\" || "$val" == \'*\' ]]; then val="${val:1:${#val}-2}"; fi
        case "$key" in
            ID) TG_OSR_ID="$val" ;;
            VERSION_ID) TG_OSR_VERSION_ID="$val" ;;
            VERSION_CODENAME) TG_OSR_CODENAME="$val" ;;
        esac
    done < "$f"
    if [[ $n -eq 0 ]]; then TG_OSR_ERR="$f is empty"; return 1; fi
    return 0
}

tg_host_platform() {
    local arch bad=0 why="these packages and their Debian dependencies are built, simulated and supported only for 64-bit Raspberry Pi OS / Debian 13 (trixie) on arm64 (Raspberry Pi 5)"
    arch="$("$DPKG" --print-architecture 2>/dev/null)"
    if [[ "$arch" == "$TG_REQ_ARCH" ]]; then
        tg_ok "host architecture: $arch"
    else
        tg_fail "host architecture: found '${arch:-<nothing: dpkg --print-architecture failed>}', expected '$TG_REQ_ARCH'. Why: $why."
        bad=1
    fi
    if ! tg_parse_os_release "$OS_RELEASE"; then
        tg_fail "host OS: $TG_OSR_ERR; expected a valid os-release with ID=$TG_REQ_ID, VERSION_ID=$TG_REQ_VERSION_ID, VERSION_CODENAME=$TG_REQ_CODENAME. Why: the OS cannot be identified, so compatibility cannot be checked."
        bad=1
    else
        local found="ID=${TG_OSR_ID:-<missing>} VERSION_ID=${TG_OSR_VERSION_ID:-<missing>} VERSION_CODENAME=${TG_OSR_CODENAME:-<missing>}"
        if [[ "$TG_OSR_ID" == "$TG_REQ_ID" && "$TG_OSR_VERSION_ID" == "$TG_REQ_VERSION_ID" && "$TG_OSR_CODENAME" == "$TG_REQ_CODENAME" ]]; then
            tg_ok "host OS: $found"
        else
            tg_fail "host OS: found $found, expected ID=$TG_REQ_ID VERSION_ID=$TG_REQ_VERSION_ID VERSION_CODENAME=$TG_REQ_CODENAME. Why: $why."
            bad=1
        fi
    fi
    return $bad
}

# hard stop used by all three entry scripts: nothing (no apt, no backup, no file) happens before this passes
tg_require_host() {
    tg_say "== Host platform (hard requirement)"
    if ! tg_host_platform; then
        tg_say ""
        tg_say "HOST REJECTED: this is not a supported 64-bit Raspberry Pi OS / Debian 13 (trixie) arm64 system."
        tg_say "Nothing was checked further and nothing was changed (no apt call, no backup)."
        exit 1
    fi
}

# every deb must be Architecture all or arm64 (FAIL otherwise)
tg_deb_arch() {
    local d a
    for d in "$@"; do
        a="$("$DPKG_DEB" -f "$d" Architecture 2>/dev/null)"
        case "$a" in all|arm64) tg_ok "$(/usr/bin/basename "$d"): Architecture $a" ;;
                     *) tg_fail "$(/usr/bin/basename "$d"): Architecture '${a:-unreadable}' is not all/arm64" ;; esac
    done
}

tg_sha() {
    if ( cd "$1" && /usr/bin/sha256sum --quiet -c SHA256SUMS >/dev/null 2>&1 ); then tg_ok "SHA256SUMS verified"; else tg_fail "SHA256SUMS mismatch or missing in $1"; fi
}

# tg_require "pkg" "minver" "why"
tg_require() {
    local v; v="$(tg_ver "$1" || true)"
    if [ -n "$v" ] && ! tg_lt "$v" "$2"; then tg_ok "$1 $v (>= $2)"; else tg_fail "$1 ${v:-not installed} < $2: $3"; fi
}

# tg_target "pkg" "newver": never downgrade
tg_target() {
    local v; v="$(tg_ver "$1" || true)"
    if [ -z "$v" ]; then tg_ok "$1: not installed -> $2"
    elif tg_gt "$v" "$2"; then tg_fail "$1 $v is newer than $2: refusing to downgrade"
    elif [ "$v" = "$2" ]; then tg_warn "$1 $2 is already installed (apt will reinstall nothing / report no change)"
    else tg_ok "$1 $v -> $2"; fi
}

tg_closed() {
    local p
    for p in "$@"; do
        if "$PGREP" -u "$("$ID" -u)" -f "$p" >/dev/null 2>&1; then tg_fail "close the running program matching '$p' first"; fi
    done
}

# SoapySDR left behind by the 0.2.x Depends->Suggests change: warn only, never apt-mark.
tg_soapy_warn() {
    local auto p v
    auto="$("$APT_MARK" showauto 2>/dev/null)"
    for p in python3-soapysdr soapysdr0.8-module-rtlsdr; do
        v="$(tg_ver "$p" || true)"
        [ -n "$v" ] || continue
        if printf '%s\n' "$auto" | /usr/bin/grep -qx "$p"; then
            tg_warn "$p $v is marked automatically installed. task-sdr >= 0.2.0 only Suggests it, so apt may now list it as autoremovable. This installer never autoremoves and does NOT change marks. To keep it permanently, run yourself:  sudo apt-mark manual $p"
        else
            tg_ok "$p $v is manually installed (not autoremovable)"
        fi
    done
}

# tg_apt_sim "allowed-downgrade pkgs (space separated, may be empty)" deb...
# FAILS on: nonzero exit, any Remv/Purg line, E: lines, unmet/broken deps, any downgrade not explicitly allowed.
TG_SIM_OUT=""
tg_apt_sim() {
    local allow="$1"; shift
    local args=(-s -o Debug::NoLocking=1 install --no-remove)
    [ -n "$allow" ] && args+=(--allow-downgrades)
    local out rc line pkg old new
    out="$("$APT_GET" "${args[@]}" "$@" 2>&1)"; rc=$?
    TG_SIM_OUT="$out"
    tg_say "  apt-get ${args[*]} <debs>  -> exit $rc"
    printf '%s\n' "$out" | /usr/bin/grep -E '^(Inst|Conf|Remv|Purg|E:|W:)' | /usr/bin/sed 's/^/      /'
    [ "$rc" -eq 0 ] || tg_fail "apt-get simulation exited $rc (dependency problem or broken packages); nothing can be installed"
    while IFS= read -r line; do
        tg_fail "apt would REMOVE something: $line"
    done < <(printf '%s\n' "$out" | /usr/bin/grep -E '^(Remv|Purg) ')
    if printf '%s\n' "$out" | /usr/bin/grep -qE '^E: |unmet dependencies|held broken packages|Broken '; then
        tg_fail "apt reports errors / broken or unmet dependencies"
    fi
    while IFS= read -r line; do
        # Inst pkg [old] (new source [arch])
        pkg="$(printf '%s' "$line" | /usr/bin/awk '{print $2}')"
        old="$(printf '%s' "$line" | /usr/bin/sed -n 's/^Inst [^ ]* \[\([^]]*\)\].*/\1/p')"
        new="$(printf '%s' "$line" | /usr/bin/sed -n 's/^Inst [^(]*(\([^ ]*\) .*/\1/p')"
        [ -n "$old" ] && [ -n "$new" ] || continue
        if tg_lt "$new" "$old"; then
            case " $allow " in
                *" $pkg "*) tg_ok "rollback downgrade $pkg $old -> $new (explicitly requested)" ;;
                *) tg_fail "apt would DOWNGRADE $pkg $old -> $new" ;;
            esac
        fi
    done < <(printf '%s\n' "$out" | /usr/bin/grep -E '^Inst ')
    if [ "$rc" -eq 0 ] && ! printf '%s\n' "$out" | /usr/bin/grep -qE '^Inst '; then
        tg_warn "apt has nothing to install (already at these versions?)"
    fi
}

# tg_confirm "PHRASE" : explicit typed confirmation
tg_confirm() {
    local a
    tg_say ""
    tg_say "To continue type exactly:  $1"
    IFS= read -r -p "> " a || a=""
    if [ "$a" != "$1" ]; then tg_say "Not confirmed; nothing changed."; return 1; fi
}

tg_backup_dpkg_state() {
    local d="$1/dpkg-state"
    /usr/bin/mkdir -p "$d"
    "$DPKG" -l > "$d/dpkg-l.txt" 2>&1 || true
    "$DPKGQ" -W -f='${Package}\t${Version}\t${Status}\n' > "$d/dpkg-query.tsv" 2>&1 || true
    "$APT_MARK" showmanual > "$d/apt-mark-manual.txt" 2>&1 || true
    "$APT_MARK" showauto > "$d/apt-mark-auto.txt" 2>&1 || true
    "$DPKG" --print-architecture > "$d/architecture.txt" 2>&1 || true
    /usr/bin/cp -- "$OS_RELEASE" "$d/os-release" 2>/dev/null || true
}
