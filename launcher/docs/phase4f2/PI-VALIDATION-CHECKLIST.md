# Phase 4F.2 Pi checklist — UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST
1. `bash preflight-phase4f2.sh`: shows launcher 0.3.3 and task-mesh 0.3.1 (4F.1). Nothing changes.
2. `./install-phase4f2.sh`, then `--install`, type yes. `dpkg-query -W task-launcher` = 0.3.4.
3. Restart the launcher (log out/in or close and reopen). All 12 tiles are present, Medical included.
4. Tap Medical: the view opens inside the launcher window; no new window appears in the taskbar.
5. Back returns to Home; Home returns to Home. Reopen 5×: still one window, `pgrep -fc task_launcher` unchanged.
6. In T.A.S.K. Resources, add the category "Medical" to one PDF. Medical → Refresh shows it; Open shows it in the desktop PDF reader.
7. With Kiwix running: medical ZIM books are listed, and Open shows them in the built-in Kiwix viewer.
8. Turn Wi-Fi off: the view still opens and lists Resources items.
9. Library tile: T.A.S.K. Resources still opens, and its other categories are unchanged.
10. Reboot, sign in, tap Medical: same behaviour.
11. `sha256sum ~/.local/share/task-resources/index.sqlite` is identical before and after steps 4–8 (with Resources closed).
