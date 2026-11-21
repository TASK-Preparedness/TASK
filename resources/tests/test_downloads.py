# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""Phase 4E: catalog, SSRF-safe client and download engine against mocked local HTTP(S) servers."""

import errno
import hashlib
import os
import time
from pathlib import Path

import pytest

import zimfactory
from httpfixture import Server, self_signed
from task_resources import catalog as cat
from task_resources import downloads as dl
from task_resources import managed
from task_resources.net import safehttp

DATA = Path(__file__).parent / "data"
TEST_POLICY = safehttp.Policy(any_port=True, allow_ips=frozenset({"127.0.0.1"}), timeout=5)


@pytest.fixture
def srv():
    s = Server()
    yield s
    s.close()


@pytest.fixture
def client():
    return safehttp.Client(TEST_POLICY)


@pytest.fixture
def mgr(library, client, tmp_path):
    m = dl.DownloadManager(library, client, tmp_path / "data/downloads.sqlite", autostart=False)
    yield m
    m.close()


@pytest.fixture
def zim_bytes(tmp_path):
    (tmp_path / "src").mkdir(exist_ok=True)
    p = zimfactory.make_zim(tmp_path / "src/Downloaded Manual.zim", title="Downloaded Manual", name="dl_manual")
    return Path(p).read_bytes()


def wait(cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ---------------------------------------------------------------------------------------------- catalog
def test_d01_catalog_parses_real_kiwix_feed():
    entries, total = cat.parse_feed((DATA / "kiwix-catalog-sample.xml").read_bytes())
    assert total == len(entries) == 8
    e = entries[0]
    assert e.uuid and "-" in e.uuid and e.name and e.title and e.publisher
    assert e.url.startswith("https://") and e.url.endswith(".zim.meta4") and e.mime == "application/x-zim"
    assert e.format == "ZIM" and e.size > 0 and e.languages
    assert {x.category for x in entries} == {"wikipedia", "gutenberg", "other", "stack_exchange"}
    assert all(not s.startswith("_") for x in entries for s in x.subjects)


def test_d02_meta4_gives_exact_size_sha256_and_mirrors():
    m = cat.parse_meta4((DATA / "kiwix-sample.meta4").read_bytes())
    assert m.name == "php.net_en_all_2024-08.zim" and m.size == 32847118
    assert m.sha256 == "e8e3549228bafaaff927078fcd87b677ed10ba23292c0c70883442bf3d742c3b"
    assert m.urls[0].startswith("https://") and len(m.urls) == 5
    assert cat.direct_url("https://x/a.zim.meta4") == "https://x/a.zim"


def test_d03_catalog_refuses_dtd_entities():
    with pytest.raises(cat.CatalogError):
        cat.parse_feed(b'<?xml version="1.0"?><!DOCTYPE f [<!ENTITY a "x">]><feed xmlns="http://www.w3.org/2005/Atom">&a;</feed>')


def test_d04_search_and_filters_local(srv, client, tmp_path):
    srv.add("/catalog/v2/entries?count=-1", data=(DATA / "kiwix-catalog-sample.xml").read_bytes(),
            ctype="application/atom+xml")
    c = cat.Catalog(srv.url("/catalog/v2"), client, tmp_path / "cache")
    assert c.refresh() and c.online and len(c.entries) == 8
    cats, langs, pubs = c.facets()
    assert "wikipedia" in cats and "eng" in langs and pubs
    assert all(e.category == "gutenberg" for e in c.search(category="gutenberg")) and c.search(category="gutenberg")
    assert all("fra" in e.languages for e in c.search(lang="fra"))
    small = c.search(max_size=50 * 1024 * 1024)
    assert small and all(e.size <= 50 * 1024 * 1024 for e in small)
    word = c.entries[0].title.split()[0]
    assert c.entries[0] in c.search(q=word.lower())
    assert c.search(q="zzzz-no-such-thing") == []


def test_d05_catalog_cache_offline_and_server_down(srv, client, tmp_path):
    srv.add("/catalog/v2/entries?count=-1", data=(DATA / "kiwix-catalog-sample.xml").read_bytes())
    c = cat.Catalog(srv.url("/catalog/v2"), client, tmp_path / "cache")
    assert c.refresh()
    assert oct(os.stat(tmp_path / "cache/catalog").st_mode & 0o777) == "0o700"
    srv.routes["/catalog/v2/entries?count=-1"].status = 503         # server down
    c2 = cat.Catalog(srv.url("/catalog/v2"), client, tmp_path / "cache")
    assert c2.refresh() is False and c2.online is False and "503" in c2.error
    assert len(c2.entries) == 8 and c2.fetched_at > 0                # cached copy still browsable
    srv.close()                                                      # network gone entirely
    c3 = cat.Catalog(srv.url("/catalog/v2"), client, tmp_path / "cache")
    assert c3.refresh() is False and len(c3.entries) == 8


def test_d06_installed_detection_and_duplicate_prevention(library, mgr, tmp_path, zim):
    from conftest import register
    rid = register(library, zim)
    uuid = library.index.get(rid)["zim_uuid"]
    e = cat.Entry(uuid=uuid, title="Field Manual", url="https://download.kiwix.org/zim/x.zim.meta4")
    assert cat.installed(library.index, e) == rid
    with pytest.raises(dl.Duplicate):
        mgr.add_catalog_entry(e)
    t = mgr.add("https://example.org/a.pdf")
    with pytest.raises(dl.Duplicate):
        mgr.add("https://example.org/a.pdf")
    assert mgr.get(t)["state"] == dl.QUEUED


# ---------------------------------------------------------------------------------------------- security
@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.10", "169.254.169.254",
                                "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1",
                                "::ffff:127.0.0.1", "::ffff:10.0.0.1", "2002:0a00:0001::1"])
def test_d07_private_addresses_are_not_public(ip):
    assert safehttp.ip_is_public(ip) is False


def test_d08_public_addresses_allowed_and_url_rules():
    assert safehttp.ip_is_public("93.184.216.34") and safehttp.ip_is_public("2606:4700::1111")
    p = safehttp.Policy()
    for bad in ("file:///etc/passwd", "ftp://x/y", "https://user:pw@example.org/a", "http://example.org:8080/a",
                "javascript:alert(1)", "https:///nohost"):
        with pytest.raises(safehttp.Blocked):
            safehttp.check_url(bad, p)
    assert safehttp.check_url("https://example.org/a?b=1", p) == ("https", "example.org", 443, "/a?b=1")
    assert safehttp.redact("https://example.org/a?token=secret") == "https://example.org/a"


def test_d09_default_policy_blocks_loopback_and_dns_rebinding(srv):
    srv.add("/x", data=b"secret")
    with pytest.raises(safehttp.Blocked):
        safehttp.Client(safehttp.Policy(any_port=True)).request(srv.url("/x"))
    # a name that resolves to a public AND a private address is refused (rebinding / split answers)
    res = lambda h, p, type=0: [(2, 1, 6, "", ("93.184.216.34", p)), (2, 1, 6, "", ("127.0.0.1", p))]  # noqa
    with pytest.raises(safehttp.Blocked):
        safehttp.Client(safehttp.Policy(any_port=True), resolver=res).request(f"http://rebind.example:{srv.port}/x")
    assert srv.routes["/x"].hits == []


def test_d10_every_redirect_hop_is_validated(srv):
    srv.add("/start", redirect="http://169.254.169.254/latest/meta-data/")
    srv.add("/loop", redirect="/loop")
    c = safehttp.Client(TEST_POLICY)
    with pytest.raises(safehttp.Blocked, match="local/private"):
        c.request(srv.url("/start"))
    with pytest.raises(safehttp.Blocked, match="too many redirects"):
        c.request(srv.url("/loop"))
    assert len(srv.routes["/loop"].hits) == TEST_POLICY.max_redirects + 1


def test_d11_https_certificate_is_verified(tmp_path):
    crt, key = self_signed(tmp_path)
    s = Server(tls_cert=(crt, key))
    try:
        s.add("/f.txt", data=b"hello", ctype="text/plain")
        with pytest.raises(safehttp.Blocked, match="certificate"):
            safehttp.Client(TEST_POLICY).request(s.url("/f.txt"))
        import ssl
        ctx = ssl.create_default_context(cafile=crt)
        data, _ = safehttp.Client(TEST_POLICY, ssl_context=ctx).get_bytes(s.url("/f.txt"), 100)
        assert data == b"hello"
    finally:
        s.close()


@pytest.mark.parametrize("raw,want", [("../../etc/passwd", "passwd"), ("..%2F..%2Fx.pdf", "x.pdf"),
                                      ("a\x00b.pdf", "ab.pdf"), ("", "download"), ("..", "download"),
                                      ("weird name<>|.PDF", "weird name___.pdf")])
def test_d12_filename_sanitising(raw, want):
    assert dl.sanitize_filename(raw) == want


def test_d13_only_document_types_allowed():
    assert dl.choose_filename("https://x/a/notes.md") == "notes.md"
    assert dl.choose_filename("https://x/get?id=3", 'attachment; filename="Guide.pdf"') == "Guide.pdf"
    assert dl.choose_filename("https://x/page", "", "text/html; charset=utf-8") == "page.html"
    for bad in ("https://x/setup.sh", "https://x/a.deb", "https://x/run.exe", "https://x/a.py"):
        with pytest.raises(dl.DownloadError):
            dl.choose_filename(bad, "", "application/octet-stream")


# ---------------------------------------------------------------------------------------------- downloads
def test_d14_zim_download_verified_registered_progress(library, mgr, srv, zim_bytes, settings):
    srv.add("/zim/manual.zim", data=zim_bytes, ctype="application/octet-stream")
    tid = mgr.add(srv.url("/zim/manual.zim"), ["Medical", "Field"],
                  expected_sha256=hashlib.sha256(zim_bytes).hexdigest())
    seen = []
    orig = mgr._set
    mgr._set = lambda i, **kw: (seen.append(dict(kw)), orig(i, **kw))[1]
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.DONE, t
    final = Path(t["final_path"])
    assert final.parent == Path(settings.managed_root) / "Medical" and final.name == "manual.zim"
    assert final.read_bytes() == zim_bytes and not list(final.parent.glob(".*part*"))
    assert oct(final.stat().st_mode & 0o777) == "0o644"          # never executable
    r = library.index.get(t["rid"])
    assert r["managed"] == 1 and r["kind"] == "zim" and r["sha256"] == hashlib.sha256(zim_bytes).hexdigest()
    assert r["categories"] == ["Field", "Medical"]                 # several categories (tags) per resource
    assert t["rid"] in mgr.completed
    assert any(s.get("state") == dl.VERIFYING for s in seen) and t["total"] == len(zim_bytes)
    assert "sha256 verified" in t["note"]


def test_d15_pause_resume_uses_range_and_if_range(library, client, srv, tmp_path):
    data = os.urandom(3 * 1024 * 1024)
    route = srv.add("/big.pdf", data=b"%PDF-1.4\n" + data, ctype="application/pdf", delay=0.03, etag='"abc"')
    m = dl.DownloadManager(library, client, tmp_path / "d.sqlite", autostart=True)
    try:
        tid = m.add(srv.url("/big.pdf"), ["Docs"])
        assert wait(lambda: (m.get(tid)["done"] or 0) > 200_000)
        m.pause(tid)
        assert wait(lambda: m.get(tid)["state"] == dl.PAUSED)
        t = m.get(tid)
        part = Path(library.settings.managed_root) / "Docs" / ".big.pdf.part"
        assert part.is_file() and 0 < part.stat().st_size < len(route.data)
        paused_at = part.stat().st_size
        assert dl.eta(t["done"], t["total"], 1000.0) > 0
        route.delay = 0
        m.resume(tid)
        assert wait(lambda: m.get(tid)["state"] == dl.DONE)
        assert route.hits[-1].get("Range") == f"bytes={paused_at}-"
        assert route.hits[-1].get("If-Range") == '"abc"'
        assert Path(m.get(tid)["final_path"]).read_bytes() == route.data
    finally:
        m.close()


def test_d16_server_without_range_restarts_safely(library, mgr, srv, settings):
    body = b"%PDF-1.4\n" + os.urandom(400_000)
    route = srv.add("/norange.pdf", data=body, ctype="application/pdf", ranges=False, cut_after=100_000, etag="")
    tid = mgr.add(srv.url("/norange.pdf"), ["Docs"])
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.WAITING and "closed early" in t["error"] and t["attempts"] == 1
    assert t["next_try"] - time.time() >= 25                         # backoff, no hammering
    mgr.resume(tid)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.DONE
    assert "Range" not in route.hits[0] and "Range" not in route.hits[1]   # no validator -> no Range sent
    assert Path(t["final_path"]).read_bytes() == body and len(route.hits) == 2


def test_d17_interrupted_transfer_resumes_from_part(library, mgr, srv):
    body = b"%PDF-1.4\n" + os.urandom(500_000)
    route = srv.add("/cut.pdf", data=body, ctype="application/pdf", cut_after=200_000)
    tid = mgr.add(srv.url("/cut.pdf"), ["Docs"])
    mgr.run_one(tid)
    assert mgr.get(tid)["state"] == dl.WAITING and mgr.get(tid)["done"] == 200_000
    mgr.resume(tid)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.DONE and Path(t["final_path"]).read_bytes() == body
    assert route.hits[1]["Range"] == "bytes=200000-"


def test_d18_power_loss_recovery_and_queue_persistence(library, client, srv, tmp_path):
    body = b"%PDF-1.4\n" + os.urandom(300_000)
    srv.add("/p.pdf", data=body, ctype="application/pdf", cut_after=120_000)
    db = tmp_path / "pl.sqlite"
    m = dl.DownloadManager(library, client, db, autostart=False)
    tid = m.add(srv.url("/p.pdf"), ["Docs"])
    q2 = m.add(srv.url("/later.pdf"), ["Docs"])
    m.run_one(tid)
    m._set(tid, state=dl.RUNNING)                                      # simulate a power cut mid-transfer
    m.db.close()
    m2 = dl.DownloadManager(library, client, db, autostart=False)      # restart
    try:
        assert m2.get(tid)["state"] == dl.PAUSED and "interrupted" in m2.get(tid)["note"]
        assert m2.get(q2)["state"] == dl.QUEUED                        # queue preserved
        m2.resume(tid)
        m2.run_one(tid)
        assert m2.get(tid)["state"] == dl.DONE and Path(m2.get(tid)["final_path"]).read_bytes() == body
    finally:
        m2.close()


def test_d19_cancel_deletes_part_and_never_registers(library, client, srv, tmp_path):
    route = srv.add("/slow.pdf", data=b"%PDF-1.4\n" + os.urandom(2_000_000), ctype="application/pdf", delay=0.03)
    m = dl.DownloadManager(library, client, tmp_path / "c.sqlite", autostart=True)
    try:
        n0 = len(library.index.list())
        tid = m.add(srv.url("/slow.pdf"), ["Docs"])
        assert wait(lambda: (m.get(tid)["done"] or 0) > 100_000)
        m.cancel(tid)
        assert wait(lambda: m.get(tid)["state"] == dl.CANCELLED)
        d = Path(library.settings.managed_root) / "Docs"
        assert not list(d.glob("*")) and not list(d.glob(".*"))
        assert len(library.index.list()) == n0 and route.hits
    finally:
        m.close()


def test_d20_bad_checksum_is_kept_aside_not_registered(library, mgr, srv):
    body = b"%PDF-1.4\n" + os.urandom(50_000)
    srv.add("/bad.pdf", data=body, ctype="application/pdf")
    tid = mgr.add(srv.url("/bad.pdf"), ["Docs"], expected_sha256="0" * 64)
    mgr.run_one(tid)
    t = mgr.get(tid)
    d = Path(library.settings.managed_root) / "Docs"
    assert t["state"] == dl.FAILED and "sha256 mismatch" in t["error"] and t["rid"] is None
    assert not (d / "bad.pdf").exists() and (d / ".bad.pdf.part-failed").is_file()
    assert library.index.list() == []


def test_d21_malformed_zim_rejected(library, mgr, srv, zim_bytes):
    bad = bytearray(zim_bytes)
    mid = len(bad) // 2
    bad[mid:mid + 64] = b"\xff" * 64
    srv.add("/broken.zim", data=bytes(bad))
    srv.add("/notzim.zim", data=b"<html>this is not a zim</html>" * 100, ctype="text/html")
    for path in ("/broken.zim", "/notzim.zim"):
        tid = mgr.add(srv.url(path), ["Z"])
        mgr.run_one(tid)
        t = mgr.get(tid)
        assert t["state"] == dl.FAILED and t["rid"] is None, t
        assert ("ZIM" in t["error"]) or ("content" in t["error"])
    assert library.index.list() == []


def test_d22_disk_full_precheck_and_enospc(library, mgr, srv, monkeypatch):
    body = b"%PDF-1.4\n" + os.urandom(300_000)
    srv.add("/f.pdf", data=body, ctype="application/pdf")
    library.settings.free_space_reserve_mb = 1
    real = dl.shutil.disk_usage
    monkeypatch.setattr(dl.shutil, "disk_usage", lambda p: real(p)._replace(free=1024 * 1024 + 1000))
    tid = mgr.add(srv.url("/f.pdf"), ["Docs"])
    mgr.run_one(tid)
    assert mgr.get(tid)["state"] == dl.FAILED and "not enough free space" in mgr.get(tid)["error"]
    monkeypatch.setattr(dl.shutil, "disk_usage", real)
    library.settings.free_space_reserve_mb = 0
    real_fdopen = dl.os.fdopen

    class Full:
        def __init__(self, f):
            self.f, self.n = f, 0

        def write(self, b):
            self.n += len(b)
            if self.n > 100_000:
                raise OSError(errno.ENOSPC, "No space left on device")
            return self.f.write(b)

        def __getattr__(self, k):
            return getattr(self.f, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

    monkeypatch.setattr(dl.os, "fdopen", lambda fd, mode: Full(real_fdopen(fd, mode)))
    mgr.retry(tid)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.FAILED and t["error"] == "disk full" and t["rid"] is None
    monkeypatch.setattr(dl.os, "fdopen", real_fdopen)
    mgr.retry(tid)                                                   # after freeing space: resumes
    mgr.run_one(tid)
    assert mgr.get(tid)["state"] == dl.DONE and Path(mgr.get(tid)["final_path"]).read_bytes() == body


def test_d23_offline_waits_with_backoff_and_preserves_queue(library, mgr, srv):
    url = srv.url("/x.pdf")
    srv.close()                                                      # offline
    tid = mgr.add(url, ["Docs"])
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.WAITING and "network unavailable" in t["note"]
    mgr.run_one(tid)
    t2 = mgr.get(tid)
    assert t2["attempts"] == 2 and t2["next_try"] - time.time() > 50     # 30 s, then 60 s
    mgr._set(tid, next_try=0)
    mgr.set_offline(True)                     # offline mode: worker picks nothing, queue row kept
    mgr.start()
    time.sleep(1.5)
    assert mgr.get(tid)["state"] == dl.WAITING and mgr.get(tid)["attempts"] == 2


def test_d24_size_limit_and_size_mismatch(library, mgr, srv):
    body = b"%PDF-1.4\n" + os.urandom(10_000)
    srv.add("/s.pdf", data=body, ctype="application/pdf")
    tid = mgr.add(srv.url("/s.pdf"), ["Docs"], expected_size=999)
    mgr.run_one(tid)
    assert mgr.get(tid)["state"] == dl.FAILED and "differs" in mgr.get(tid)["error"]
    library.settings.max_download_gb = 0
    tid2 = mgr.add(srv.url("/s.pdf") + "?2", ["Docs"])
    srv.add("/s.pdf?2", data=body, ctype="application/pdf")
    mgr.run_one(tid2)
    assert mgr.get(tid2)["state"] == dl.FAILED and "size limit" in mgr.get(tid2)["error"]


def test_d25_never_overwrites_existing_file(library, mgr, srv, settings):
    d = Path(settings.managed_root) / "Docs"
    d.mkdir(parents=True)
    (d / "same.txt").write_text("user's own file\n")
    srv.add("/same.txt", data=b"downloaded text\n", ctype="text/plain")
    tid = mgr.add(srv.url("/same.txt"), ["Docs"])
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.DONE and Path(t["final_path"]).name == "same (1).txt"
    assert (d / "same.txt").read_text() == "user's own file\n"


def test_d26_existing_library_untouched_and_safe_removal(library, mgr, srv, settings, zim, tmp_path):
    from conftest import register
    st = os.stat(zim)
    digest = hashlib.sha256(Path(zim).read_bytes()).hexdigest()
    ext_rid = register(library, zim)
    srv.add("/m.md", data=b"# Notes\n", ctype="text/markdown")
    tid = mgr.add(srv.url("/m.md"), ["Notes"])
    mgr.run_one(tid)
    t = mgr.get(tid)
    with pytest.raises(managed.ManagedError, match="protected"):
        managed.remove_managed(library.index, settings, ext_rid)
    assert os.path.exists(zim) and os.stat(zim).st_mtime == st.st_mtime
    assert hashlib.sha256(Path(zim).read_bytes()).hexdigest() == digest
    u = managed.usage(settings, library.index)
    assert u["managed_count"] == 1 and u["free"] > 0
    assert managed.remove_managed(library.index, settings, t["rid"]) == t["final_path"]
    assert not os.path.exists(t["final_path"]) and library.index.get(t["rid"]) is None
    assert library.index.get(ext_rid) is not None


def test_d27_catalog_meta4_flow_end_to_end(library, mgr, srv, zim_bytes):
    sha = hashlib.sha256(zim_bytes).hexdigest()
    meta4 = (DATA / "kiwix-sample.meta4").read_text()
    meta4 = meta4.replace("e8e3549228bafaaff927078fcd87b677ed10ba23292c0c70883442bf3d742c3b", sha)
    meta4 = meta4.replace("<size>32847118</size>", f"<size>{len(zim_bytes)}</size>")
    srv.add("/zim/other/php.zim.meta4", data=meta4.encode(), ctype="application/metalink4+xml")
    srv.add("/zim/other/php.zim", redirect="/mirror/php.zim")
    srv.add("/mirror/php.zim", data=zim_bytes)
    e = cat.Entry(uuid="00000000-0000-0000-0000-000000000001", title="PHP", category="other",
                  url=srv.url("/zim/other/php.zim.meta4"), mime="application/x-zim")
    tid = mgr.add_catalog_entry(e)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert t["state"] == dl.DONE, t
    assert Path(t["final_path"]).name == "php.net_en_all_2024-08.zim" and t["expected_sha256"] == sha
    assert library.index.get(t["rid"])["kind"] == "zim"


def test_d28_server_ignoring_range_header_restarts_from_zero(library, mgr, srv):
    """Server advertises an ETag but answers a Range request with 200: the .part is truncated, not appended."""
    body = b"%PDF-1.4\n" + os.urandom(300_000)
    route = srv.add("/ign.pdf", data=body, ctype="application/pdf", cut_after=100_000, etag='"e1"')
    tid = mgr.add(srv.url("/ign.pdf"), ["Docs"])
    mgr.run_one(tid)
    route.ranges = False
    mgr.resume(tid)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert route.hits[1]["Range"] == "bytes=100000-" and t["state"] == dl.DONE
    assert "restarted from 0" in t["note"]
    assert Path(t["final_path"]).read_bytes() == body


def test_d29_changed_file_etag_restarts(library, mgr, srv):
    """If-Range mismatch (file changed on the server) -> full 200 response -> restart, no corrupt mix."""
    old = b"%PDF-1.4\n" + b"A" * 300_000
    route = srv.add("/chg.pdf", data=old, ctype="application/pdf", cut_after=100_000, etag='"old"')
    tid = mgr.add(srv.url("/chg.pdf"), ["Docs"])
    mgr.run_one(tid)
    new = b"%PDF-1.4\n" + b"B" * 250_000
    route.data, route.etag = new, '"new"'
    mgr.resume(tid)
    mgr.run_one(tid)
    t = mgr.get(tid)
    assert route.hits[1]["If-Range"] == '"old"' and t["state"] == dl.DONE
    assert Path(t["final_path"]).read_bytes() == new


def test_d30_audit_default_storage_is_per_user_and_library_is_protected(tmp_path, monkeypatch, library, mgr):
    from task_resources import settings as sm
    s = sm.Settings()
    assert s.managed_root == "~/.local/share/task-resources/downloads" and s.protected_roots == ["/library"]
    root, note = managed.resolve_root(s)
    assert str(root) == os.path.expanduser("~/.local/share/task-resources/downloads") and note == ""
    p = tmp_path / "old.json"                       # a 0.1.0/0.2.0 settings file with the old default
    p.write_text('{"managed_root": "/library/task-resources", "viewer": "lightweight", "schema": 1}')
    m = sm.load(p)
    assert m.managed_root == s.managed_root and m.viewer == "lightweight" and m.schema == 2
    p.write_text('{"managed_root": "/srv/mine", "schema": 1}')
    assert sm.load(p).managed_root == "/srv/mine"   # an explicit user choice is kept
    s.managed_root = "/library/task-resources"      # even if set again: refused, per-user fallback
    root, note = managed.resolve_root(s)
    assert not str(root).startswith("/library") and "protected" in note
    for d in ("/library", "/library/zims/content", "/library/task-resources"):
        with pytest.raises(dl.DownloadError, match="protected"):
            mgr.add("https://example.org/a.pdf", ["Docs"], dest_dir=d)
