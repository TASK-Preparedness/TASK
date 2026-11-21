# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4A: Kiwix / IIAB endpoint discovery (no hard-coded endpoint is trusted without a verified
reply), OPDS catalog / search / library XML parsing, loopback-only page fetching."""

import pytest

from p4helpers import DATA, FakeKiwix
from task_launcher.services import kiwix, probe
from task_launcher.services.probe import ProcInfo, Unit


@pytest.mark.parametrize("argv,port,root,lib", [
    (["/opt/iiab/kiwix/bin/kiwix-serve", "--daemon", "--port", "3000", "--nolibrarybutton", "--library",
      "/library/zims/library.xml", "--urlRootLocation=/kiwix/", "--threads", "4"], 3000, "/kiwix/",
     ["/library/zims/library.xml"]),
    (["/usr/bin/kiwix-serve", "-p8080", "-r", "wiki", "--library", "/a.xml;/b.xml"], 8080, "/wiki/", ["/a.xml", "/b.xml"]),
    (["/usr/bin/kiwix-serve", "--port=9000", "-t", "2", "/srv/a.zim", "/srv/b.zim"], 9000, "/", []),
    (["/usr/bin/kiwix-serve", "/srv/a.zim"], 80, "/", []),
])
def test_parse_serve_argv(argv, port, root, lib):
    a = kiwix.parse_serve_argv(argv)
    assert (a["port"], a["root"], a["library"]) == (port, root, lib)


def test_parse_serve_argv_not_kiwix():
    assert kiwix.parse_serve_argv(["/usr/bin/python3"]) is None


def test_parse_exec_start():
    text = ("ExecStart={ path=/opt/iiab/kiwix/bin/kiwix-serve ; argv[]=/opt/iiab/kiwix/bin/kiwix-serve --daemon "
            "--port 3000 --library /library/zims/library.xml --urlRootLocation=/kiwix/ ; ignore_errors=no ; "
            "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }")
    assert probe.parse_exec_start(text)[:4] == ["/opt/iiab/kiwix/bin/kiwix-serve", "--daemon", "--port", "3000"]


def test_list_units_uses_readonly_systemctl_queries():
    calls = []

    def runner(argv, **k):
        calls.append(argv)
        if "list-units" in argv:
            return 0, "kiwix-serve.service loaded active running Provides the Kiwix ZIM File Server\n"
        return 0, "ExecStart={ path=/x ; argv[]=/opt/iiab/kiwix/bin/kiwix-serve --port 3000 ; ignore_errors=no }\n"

    units = probe.list_units(["kiwix*"], runner=runner)
    assert units[0].name == "kiwix-serve.service" and units[0].active == "active"
    assert units[0].exec_argv == ["/opt/iiab/kiwix/bin/kiwix-serve", "--port", "3000"]
    for argv in calls:
        assert argv[0] == "/usr/bin/systemctl" and ("list-units" in argv or "show" in argv)
        assert not {"start", "stop", "restart", "enable", "disable", "kill"} & set(argv)


def test_read_iiab(tmp_path):
    (tmp_path / "local_vars.yml").write_text("kiwix_install: True\nkiwix_port: 3100   # changed\n")
    (tmp_path / "default_vars.yml").write_text("kiwix_port: 3000\nkiwix_url: /kiwix\niiab_zim_path: /library/zims\n")
    d = kiwix.read_iiab([tmp_path / "local_vars.yml", tmp_path / "missing.yml", tmp_path / "default_vars.yml"])
    assert d["kiwix_port"] == "3100" and d["kiwix_url"] == "/kiwix" and d["iiab_zim_path"] == "/library/zims"


def _discover(units=(), procs=(), iiab=None, libs=(), **kw):
    return kiwix.discover(units_fn=lambda: list(units), procs_fn=lambda: list(procs),
                          iiab_fn=lambda: dict(iiab or {}), binaries_fn=lambda: {"kiwix-serve": "/usr/bin/kiwix-serve"},
                          library_candidates=libs, **kw)


def test_discover_from_systemd_unit_verified(local_port, tmp_path):
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        u = Unit("kiwix-serve.service", "active", "running",
                 exec_argv=["/opt/iiab/kiwix/bin/kiwix-serve", "--port", str(fk.port), "--library",
                            str(DATA / "library.xml"), "--urlRootLocation=/kiwix/"])
        st = _discover(units=[u])
    assert st.ready and st.endpoint.port == fk.port and st.endpoint.root == "/kiwix/"
    assert "systemd unit kiwix-serve.service" in st.endpoint.source
    assert [b.name for b in st.books] == ["testwiki_en_mini", "mdwiki_en_all_testdata", "gutenberg_testdata"]
    assert st.books[0].content_href == "/kiwix/content/testwiki_en_mini" and st.books[0].articles == 1200
    assert st.books[0].file_present is False             # library.xml path relative to p4data: content/ absent
    assert st.summary().startswith("Kiwix server ready · 3 collections")
    assert not any("8080" in c.label for c in st.candidates)   # defaults not probed once one verified


def test_discover_from_process_and_rejects_non_kiwix_reply(local_port):
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        # root "/" on that port answers 404 → not verified; then /kiwix/ from the process → verified
        procs = [ProcInfo(99, ["/usr/bin/kiwix-serve", "-p", str(fk.port), "-r", "/kiwix/", "x.zim"])]
        st = _discover(procs=procs, iiab={"kiwix_port": str(fk.port), "kiwix_url": "/"})
    labels = {c.label: c.verified for c in st.candidates}
    assert labels[f"localhost:{fk.port}/kiwix/"] is True and labels[f"localhost:{fk.port}/"] is False


def test_discover_nothing_found_tries_documented_defaults_only(monkeypatch):
    asked = []

    def http(url, **k):
        asked.append(url)
        return probe.HttpResult(error="ConnectionRefusedError")

    st = kiwix.discover(units_fn=list, procs_fn=list, iiab_fn=dict, binaries_fn=dict, http=http,
                        library_candidates=())
    assert not st.ready and st.summary() == "No Kiwix server or library found"
    hosts = {u.split("/")[2] for u in asked}
    assert hosts == {"127.0.0.1:3000", "127.0.0.1:8080"}
    assert all(c.source.startswith("default candidate") for c in st.candidates)


def test_discover_offline_library_file_only(tmp_path):
    def http(url, **k):
        return probe.HttpResult(error="ConnectionRefusedError")

    st = kiwix.discover(units_fn=list, procs_fn=list, iiab_fn=dict, binaries_fn=dict, http=http,
                        library_candidates=(DATA / "library.xml",))
    assert not st.ready and st.summary() == "Kiwix library file found · server not reachable"
    assert [b.name for b in st.books] == ["testwiki_en_mini", "missing_file"]
    assert st.books[1].file_present is False


def test_unit_bound_to_lan_address_is_not_probed():
    u = Unit("kiwix.service", "active", "running", exec_argv=["/usr/bin/kiwix-serve", "-i", "192.0.2.5", "-p", "81", "a.zim"])
    asked = []
    kiwix.discover(units_fn=lambda: [u], procs_fn=list, iiab_fn=dict, binaries_fn=dict,
                   http=lambda url, **k: asked.append(url) or probe.HttpResult(error="x"), library_candidates=())
    assert not any(":81/" in a for a in asked) and all("127.0.0.1" in a for a in asked)


def test_opds_and_search_parsing():
    books = kiwix.parse_opds((DATA / "opds_entries.xml").read_bytes())
    assert books[1].tags.endswith("medicine") and books[0].size_bytes == 52428800
    res = kiwix.parse_search_xml((DATA / "search.xml").read_bytes())
    assert res.total == 2 and res.hits[0].title == "Water purification"
    assert res.hits[0].snippet == "...methods of water purification include boiling..."
    assert res.hits[0].href == "/kiwix/content/testwiki_en_mini/A/Water_purification"


def test_xml_with_dtd_refused():
    with pytest.raises(Exception):
        kiwix.parse_opds(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><feed/>')


def test_search_and_page_fetch_against_fake_server(local_port):
    with FakeKiwix("/kiwix/") as fk:
        local_port(fk.port)
        c = kiwix.Candidate(fk.port, "/kiwix/", verified=True)
        book = kiwix.Book(name="testwiki_en_mini")
        res = kiwix.search(c, book, "water")
        assert [h.title for h in res.hits] == ["Water purification", "Water"]
        assert any("books.name=testwiki_en_mini" in r and "format=xml" in r for r in fk.requests)
        url, html, err = kiwix.fetch_page(c, kiwix.absolute(c, "/kiwix/content/testwiki_en_mini"))
        assert err == "" and url.endswith("/A/Main_Page")
        assert "<script" not in html and "alert" not in html and "onclick" not in html and "TESTDATA Main Page" in html
        _, _, err = kiwix.fetch_page(c, kiwix.absolute(c, "/kiwix/goes-external"))
        assert "outside the local Kiwix server" in err


def test_absolute_and_loopback_rules():
    c = kiwix.Candidate(3000, "/kiwix/")
    assert kiwix.absolute(c, "content/x") == "http://127.0.0.1:3000/kiwix/content/x"
    assert kiwix.absolute(c, "https://example.invalid/") == ""
    assert kiwix.absolute(c, "http://127.0.0.1:9999/x") == ""
    assert kiwix.browser_url("http://127.0.0.1:3000/kiwix/") == "http://localhost:3000/kiwix/"
    assert probe.http_get("http://192.0.2.1/").error.startswith("not a loopback")
    assert probe.http_get("https://127.0.0.1/").error
    with pytest.raises(probe.NotLoopback):
        probe.tcp_reachable(80, host="example.invalid")
