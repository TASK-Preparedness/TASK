#!/bin/bash -p
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
# T.A.S.K. release PREFLIGHT (generic; settings in release.conf). READ-ONLY: changes nothing, needs no root.
# Exit 0 = ready (warnings possible), 1 = at least one FAIL, 2 = usage.
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
DEB_PATHS=()
for d in "${DEBS[@]}"; do DEB_PATHS+=("$HERE/$d"); done

tg_say "== $REL_TITLE — preflight (read-only)"
tg_say "== Integrity";  tg_sha "$HERE"
tg_say "== Package architecture"; tg_deb_arch "${DEB_PATHS[@]}"
tg_say "== Versions"
for t in "${TARGETS[@]}"; do tg_target "${t%%=*}" "${t#*=}"; done
for r in "${REQUIRES[@]}"; do tg_require "${r%%>=*}" "${r#*>=}" "install the release that provides it first"; done
tg_say "== Rollback availability"
for t in "${TARGETS[@]}"; do
    p="${t%%=*}"; v="${t#*=}"; cur="$(tg_ver "$p" || true)"
    if [ -z "$cur" ]; then tg_ok "$p not installed: rollback = leave installed (removal is never automatic)"; continue; fi
    [ "$cur" = "$v" ] && { tg_ok "$p $cur: already the target"; continue; }
    found=""
    for rb in "${ROLLBACK[@]}"; do
        IFS='=' read -r rp rv rf <<< "$rb"
        [ "$rp" = "$p" ] && [ "$rv" = "$cur" ] && found="$rf"
    done
    if [ -n "$found" ] && [ -f "$HERE/$found" ]; then tg_ok "$p $cur: rollback package $(/usr/bin/basename "$found") present"
    else tg_fail "$p $cur is installed but this zip has no rollback package for $cur (rollback could not be guaranteed)"; fi
done
tg_say "== Running programs"
tg_closed "${CLOSE_FIRST[@]}"
for p in "${WARN_RUNNING[@]}"; do
    "$PGREP" -u "$("$ID" -u)" -f "$p" >/dev/null 2>&1 && tg_warn "'$p' is running: restart it after installing (never done automatically)"
done
if [ "${SOAPY_WARN:-0}" = 1 ]; then tg_say "== SoapySDR (optional since task-sdr 0.2.0)"; tg_soapy_warn; fi
if declare -F rel_extra_checks >/dev/null; then tg_say "== Release checks"; rel_extra_checks; fi
tg_say "== apt simulation (apt-get -s; changes nothing)"
tg_apt_sim "" "${DEB_PATHS[@]}"
tg_say ""
if [ "$TG_FAIL" -gt 0 ]; then tg_say "PREFLIGHT FAILED: $TG_FAIL problem(s), $TG_WARN warning(s). Nothing was changed."; exit 1; fi
tg_say "PREFLIGHT PASSED with $TG_WARN warning(s). Nothing was changed."
exit 0
