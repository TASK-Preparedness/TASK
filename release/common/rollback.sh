#!/bin/bash -p
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. release ROLLBACK (generic). Explicit: needs the backup directory made by install.sh.
#   rollback.sh BACKUP_DIR [--restore-data]
# Reinstalls the previously installed versions from BACKUP_DIR/rollback-debs (sha256-verified) with
# `apt-get install --no-remove --allow-downgrades` after an apt simulation that may downgrade ONLY those
# packages and remove nothing. Packages that were not installed before are left installed (never removed).
# --restore-data: current settings/database are MOVED aside (never deleted), then the backup is copied back.
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
B="${1:-}"; R="${2:-}"
if [ -z "$B" ] || [ ! -f "$B/versions-before.txt" ]; then echo "usage: $0 BACKUP_DIR [--restore-data]"; exit 2; fi
B="$(cd "$B" && pwd)"
. "$B/task-guard.sh"
tg_require_host
. "$B/release.conf"
tg_not_root
case "$R" in ""|--restore-data) ;; *) tg_say "unknown option $R"; exit 2 ;; esac
tg_say "== Rollback of $REL_TITLE from $B"
tg_closed "${CLOSE_FIRST[@]}"
DEBS_RB=(); ALLOW=""
while read -r p prev; do
    cur="$(tg_ver "$p" || true)"
    if [ "$prev" = none ]; then
        tg_ok "$p was not installed before: left at ${cur:-none} (removal is your decision; not done here)"; continue
    fi
    if [ "$cur" = "$prev" ]; then tg_ok "$p already at $prev"; continue; fi
    f="$(/usr/bin/awk -v p="$p" -v v="$prev" '$1==p && $2==v {print $3}' "$B/rollback-plan.txt")"
    if [ -z "$f" ] || [ ! -f "$B/rollback-debs/$f" ]; then tg_fail "no rollback package for $p $prev in $B"; continue; fi
    want="$(/usr/bin/awk -v f="$f" '$2==f{print $1}' "$B/rollback-debs/SHA256SUMS")"
    got="$(/usr/bin/sha256sum "$B/rollback-debs/$f" | /usr/bin/cut -d' ' -f1)"
    if [ -z "$want" ] || [ "$want" != "$got" ]; then tg_fail "$f sha256 mismatch"; continue; fi
    tg_ok "$p ${cur:-none} -> $prev ($f, sha256 verified)"
    DEBS_RB+=("$B/rollback-debs/$f"); ALLOW="$ALLOW $p"
done < "$B/versions-before.txt"
if [ "${#DEBS_RB[@]}" -gt 0 ]; then
    tg_say "== apt simulation"
    tg_apt_sim "${ALLOW# }" "${DEBS_RB[@]}"
fi
[ "$TG_FAIL" -eq 0 ] || { tg_say "ROLLBACK REFUSED: $TG_FAIL problem(s). Nothing changed."; exit 1; }
[ "${#DEBS_RB[@]}" -gt 0 ] || [ "$R" = --restore-data ] || { tg_say "Nothing to roll back."; exit 0; }
tg_confirm "ROLLBACK $REL_ID" || exit 1
if [ "${#DEBS_RB[@]}" -gt 0 ]; then
    "$SUDO" "$APT_GET" install --no-remove --allow-downgrades "${DEBS_RB[@]}" || { tg_say "apt failed; data NOT restored."; exit 1; }
fi
if [ "$R" = --restore-data ]; then
    T="$(/usr/bin/date +%Y%m%d-%H%M%S)"
    for rel in "${SETTINGS[@]}"; do
        [ -e "$B/home/$rel" ] || continue
        [ -e "$HOME/$rel" ] && /usr/bin/mv -- "$HOME/$rel" "$HOME/$rel.pre-rollback-$T"
        /usr/bin/mkdir -p "$HOME/$(/usr/bin/dirname "$rel")"
        /usr/bin/cp -a -- "$B/home/$rel" "$HOME/$rel" && tg_say "  restored ~/$rel (previous kept as ~/$rel.pre-rollback-$T)"
    done
    for rel in "${SQLITE[@]}"; do
        [ -f "$B/sqlite/$rel" ] || continue
        dst="$HOME/$rel"; aside="$(/usr/bin/dirname "$dst")/pre-rollback-$T"
        /usr/bin/mkdir -p -m 0700 "$aside"
        for s in "" -wal -shm; do                         # the db+wal+shm SET moves together, never deleted
            [ -e "$dst$s" ] && /usr/bin/mv -- "$dst$s" "$aside/"
        done
        /usr/bin/cp -p -- "$B/sqlite/$rel" "$dst" && /usr/bin/chmod 0600 "$dst"
        tg_say "  restored ~/$rel (previous db/-wal/-shm set kept in $aside)"
    done
fi
tg_say ""
while read -r p prev; do tg_say "  now: $p $(tg_ver "$p" || echo none) (before install: $prev)"; done < "$B/versions-before.txt"
tg_say "Rollback finished. No service was started or enabled."
