#!/bin/bash -p
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. release INSTALLER (generic; settings in release.conf).
#   ./install.sh            check only (= preflight), changes nothing
#   ./install.sh --install  preflight -> typed confirmation -> backup -> ONE `sudo apt-get install --no-remove`
# Never: autoremove, remove/purge, apt-mark, service start/enable, overwriting configuration, firmware, radio TX.
# --- environment hardening (INSTALLER.md, "Threat model") ------------------------------------------------
# Re-run in a whitelisted environment under `bash -p` unless that is already the case. -p ignores BASH_ENV/ENV
# and imported functions; env -i drops everything else (LD_PRELOAD, APT_CONFIG, PATH, DPKG_*, PYTHON*, ...).
# Only [[ ]], case and for (shell keywords, which cannot be shadowed by functions) are used before the re-exec.
tg_env_clean=1
case "$-" in *p*) ;; *) tg_env_clean=0 ;; esac
for tg_env_v in $(compgen -e); do
    case "$tg_env_v" in
        HOME|TERM|LC_ALL|PWD|OLDPWD|SHLVL|_) ;;
        PATH) [[ "$PATH" == /usr/sbin:/usr/bin:/sbin:/bin ]] || tg_env_clean=0 ;;
        *) tg_env_clean=0 ;;
    esac
done
[[ "${LC_ALL:-}" == C ]] || tg_env_clean=0
if [[ $tg_env_clean == 0 ]]; then
    exec /usr/bin/env -i HOME="$HOME" TERM="${TERM:-dumb}" LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        /bin/bash -p "$0" "$@"
fi
unset tg_env_clean tg_env_v
set -uo pipefail
HERE="$(cd "$(/usr/bin/dirname "$0")" && pwd)"
. "$HERE/task-guard.sh"
tg_require_host
. "$HERE/release.conf"
MODE="${1:-check}"
case "$MODE" in check|--check) MODE=check ;; --install) ;; *) tg_say "usage: $0 [--install]"; exit 2 ;; esac
tg_not_root
"$HERE/preflight.sh" || { tg_say "Preflight failed: nothing changed."; exit 1; }
DEB_PATHS=()
for d in "${DEBS[@]}"; do DEB_PATHS+=("$HERE/$d"); done
tg_say ""
tg_say "Plan: back up, then: sudo apt-get install --no-remove ${DEBS[*]}"
[ "$MODE" = check ] && { tg_say "Check only; nothing changed. Run with --install to proceed."; exit 0; }
tg_confirm "INSTALL $REL_ID" || exit 1

T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
B="$HOME/task-backups/$REL_ID-$T"
/usr/bin/mkdir -p -m 0700 "$B/rollback-debs" || { tg_say "cannot create $B"; exit 1; }
tg_say "== Backup to $B"
: > "$B/versions-before.txt"
: > "$B/rollback-plan.txt"
: > "$B/rollback-debs/SHA256SUMS"
for t in "${TARGETS[@]}"; do
    p="${t%%=*}"; v="${t#*=}"; cur="$(tg_ver "$p" || true)"
    printf '%s %s\n' "$p" "${cur:-none}" >> "$B/versions-before.txt"
    [ -n "$cur" ] && [ "$cur" != "$v" ] || continue
    for rb in "${ROLLBACK[@]}"; do
        IFS='=' read -r rp rv rf <<< "$rb"
        [ "$rp" = "$p" ] && [ "$rv" = "$cur" ] || continue
        want="$(/usr/bin/awk -v f="$rf" '$2==f{print $1}' "$HERE/SHA256SUMS")"
        got="$(/usr/bin/sha256sum "$HERE/$rf" | /usr/bin/cut -d' ' -f1)"
        if [ -n "$want" ] && [ "$want" = "$got" ]; then
            /usr/bin/cp -p -- "$HERE/$rf" "$B/rollback-debs/"
            printf '%s  %s\n' "$got" "$(/usr/bin/basename "$rf")" >> "$B/rollback-debs/SHA256SUMS"
            printf '%s %s %s\n' "$p" "$cur" "$(/usr/bin/basename "$rf")" >> "$B/rollback-plan.txt"
            tg_say "  saved rollback package $(/usr/bin/basename "$rf") (sha256 verified)"
        else
            tg_say "  rollback package $rf failed verification: NOT installing. Backup: $B"; exit 1
        fi
    done
done
for rel in "${SETTINGS[@]}"; do
    if [ -e "$HOME/$rel" ]; then
        /usr/bin/mkdir -p "$B/home/$(/usr/bin/dirname "$rel")"
        /usr/bin/cp -a -- "$HOME/$rel" "$B/home/$rel" && tg_say "  saved ~/$rel"
    fi
done
for rel in "${SQLITE[@]}"; do
    src="$HOME/$rel"
    [ -f "$src" ] || continue
    /usr/bin/mkdir -p "$B/sqlite/$(/usr/bin/dirname "$rel")"
    for s in "" -wal -shm; do
        [ -e "$src$s" ] && printf '%s %s %s\n' "$rel$s" "$(/usr/bin/stat -c %s "$src$s")" \
            "$(/usr/bin/sha256sum "$src$s" | /usr/bin/cut -d' ' -f1)" >> "$B/sqlite/live-set-before.txt"
    done
    if m="$(/usr/bin/python3 -I "$HERE/tools/sqlite_backup.py" "$src" "$B/sqlite/$rel")"; then
        tg_say "  saved ~/$rel as one consistent file (SQLite backup API, mode: $m; nothing created beside it)"
    else
        tg_say "  database backup of ~/$rel failed: NOT installing. Backup: $B"; exit 1
    fi
done
tg_backup_dpkg_state "$B"
/usr/bin/mkdir -p "$B/tools"
/usr/bin/cp -p -- "$HERE/rollback.sh" "$HERE/task-guard.sh" "$HERE/release.conf" "$B/"
/usr/bin/cp -p -- "$HERE/tools/"* "$B/tools/"
printf 'release %s\ncreated %s\nfrom %s\n' "$REL_ID" "$T" "$HERE" > "$B/MANIFEST.txt"
tg_say "Backup complete: $B"
tg_say "== Installing (apt asks for your sudo password and its own confirmation)"
"$SUDO" "$APT_GET" install --no-remove "${DEB_PATHS[@]}"
rc=$?
tg_say ""
ok=1
for t in "${TARGETS[@]}"; do
    p="${t%%=*}"; v="${t#*=}"; now="$(tg_ver "$p" || true)"
    if [ "$now" = "$v" ]; then tg_ok "$p $now"; else tg_fail "$p is ${now:-not installed}, expected $v"; ok=0; fi
done
if [ "$rc" -ne 0 ] || [ "$ok" -ne 1 ]; then
    tg_say "Install did not complete (apt exit $rc). Nothing else was changed. Roll back with: $B/rollback.sh $B"; exit 1
fi
tg_say "Installed. No service was started or enabled. Restart the affected programs yourself."
tg_say "Roll back with:  $B/rollback.sh $B   (add --restore-data to also restore settings/database)"
