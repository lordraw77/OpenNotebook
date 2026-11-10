# ruff: noqa: F811 - fixtures imported from test_sources are redefined as parameters
"""M3 extended ingestion: archives, source code, images and scanned pages, web pages, summaries.

Providers are scripted fakes behind the real gateway; web fetching is replaced at the pipeline boundary
(the SSRF checks of the fetcher are tested directly).
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from types import SimpleNamespace

import litellm
import pytest

from opennotebook.ingestion import pipeline
from opennotebook.ingestion.archives import ArchiveRejected, Limits, Member, Skipped, iter_members, safe_path
from opennotebook.ingestion.chunker import chunk_document
from opennotebook.ingestion.code import parse_code
from opennotebook.ingestion.parsers import sniff
from opennotebook.ingestion.summary import parse_reply
from opennotebook.ingestion.web import Fetched, FetchError, address_allowed, fetch, normalize_url
from opennotebook.models import ModelPhase, SourceStatus
from opennotebook.providers import service
from opennotebook.providers.catalog import DiscoveredModel
from tests.test_sources import (  # noqa: F401 - fixtures
    embed_calls,
    jobs,
    node,
    run_jobs,
    search,
    setup_embedding,
    upload,
)

LIMITS = Limits(
    max_total_bytes=50 * 1024 * 1024, max_files=100, max_ratio=100, max_file_bytes=20 * 1024 * 1024
)

RADIO_C = b"""#include "radio.h"

/* Selects the radio channel used for transmission. */
int radio_set_channel(struct radio *r, int channel)
{
    if (channel < 1 || channel > 13)
        return -1;
    r->channel = channel;
    return 0;
}
"""


def make_zip(files: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16  # symlink
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


def make_png(color: str = "red") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 32), color).save(buf, format="PNG")
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, format="PDF")
    return buf.getvalue()


# --- unit: archives ------------------------------------------------------------------------------------


def test_safe_path_rejects_traversal_and_absolute_names():
    assert safe_path("src/./radio.c") == "src/radio.c"
    assert safe_path("a\\b.txt") == "a/b.txt"
    for bad in ("../etc/passwd", "/etc/passwd", "C:/x", "a/../../b", "", "./"):
        assert safe_path(bad) is None


def test_zip_members_skip_unsafe_entries():
    data = make_zip({"src/radio.c": RADIO_C, "../evil.sh": b"rm -rf /"}, symlink="link")
    items = list(iter_members(data, "zip", LIMITS))
    members = [i.path for i in items if isinstance(i, Member)]
    skipped = {i.path: i.reason for i in items if isinstance(i, Skipped)}
    assert members == ["src/radio.c"]
    assert skipped == {"../evil.sh": "unsafe path", "link": "link or special file"}


def test_zip_bomb_and_file_count_are_rejected():
    bomb = make_zip({"zeros.bin": bytes(30 * 1024 * 1024)})
    assert len(bomb) < 100_000
    with pytest.raises(ArchiveRejected, match="ratio"):
        list(iter_members(bomb, "zip", LIMITS))
    many = make_zip({f"f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(ArchiveRejected, match="more than 3 files"):
        list(iter_members(many, "zip", Limits(10**8, 3, 100, 10**8)))
    with pytest.raises(ArchiveRejected, match="uncompressed"):
        list(iter_members(make_zip({"a.txt": b"y" * 5000}), "zip", Limits(1000, 10, 10**6, 10**8)))


def test_tar_gz_is_detected_and_links_skipped():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("src/radio.c")
        info.size = len(RADIO_C)
        tar.addfile(info, io.BytesIO(RADIO_C))
        link = tarfile.TarInfo("passwd")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    data = buf.getvalue()
    assert sniff(data, "x.tgz").format == "tar" and sniff(data, "x").kind == "archive"
    items = list(iter_members(data, "tar", LIMITS))
    assert [i.path for i in items if isinstance(i, Member)] == ["src/radio.c"]
    assert [i.reason for i in items if isinstance(i, Skipped)] == ["link or special file"]


# --- unit: code ------------------------------------------------------------------------------------------


def test_code_blocks_keep_file_lines_and_symbols():
    doc = parse_code(RADIO_C.decode(), "c", "radio.c")
    blocks = {b.heading_path: (b.line_start, b.line_end) for b in doc.blocks}
    assert blocks[()] == (1, 1) and blocks[("radio_set_channel",)] == (3, 10)
    py = (
        "import os\n\n\nclass Radio:\n    def a(self):\n        return 1\n\n"
        "    def b(self):\n        return 2\n"
    )
    doc = parse_code(py, "python", "radio.py", chunk_tokens=8)
    assert [b.heading_path for b in doc.blocks] == [(), ("Radio",), ("Radio", "a"), ("Radio", "b")]
    for chunk in chunk_document(doc, 20, 2):
        assert doc.text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.line_start == doc.text.count("\n", 0, chunk.char_start) + 1
    unknown = parse_code("key: 1\n\nother:\n  - 2\n", "yaml", "a.yml")
    assert [(b.line_start, b.line_end) for b in unknown.blocks] == [(1, 1), (3, 4)]


# --- unit: web -------------------------------------------------------------------------------------------


def test_url_normalization_and_address_policy():
    assert normalize_url("HTTPS://Example.com:443/a#frag") == "https://example.com/a"
    assert normalize_url("http://example.com:8080") == "http://example.com:8080/"
    for bad in ("ftp://x.org/", "file:///etc/passwd", "http://user:pw@x.org/", "javascript:alert(1)"):
        with pytest.raises(FetchError):
            normalize_url(bad)
    for blocked in ("127.0.0.1", "10.1.2.3", "192.168.0.10", "169.254.169.254", "::1", "fc00::1", "0.0.0.0"):  # noqa: S104
        assert not address_allowed(blocked), blocked
    assert not address_allowed("::ffff:127.0.0.1")
    assert address_allowed("93.184.216.34") and address_allowed("2606:4700::1111")


async def test_fetch_refuses_internal_targets():
    for url in ("http://127.0.0.1:6379/", "http://169.254.169.254/latest/meta-data/", "http://localhost/"):
        with pytest.raises(FetchError, match="not allowed"):
            await fetch(url)


def test_summary_reply_parsing():
    summary, questions = parse_reply('Sure: {"summary": "A manual.", "questions": ["Q1?", "Q2?", "", "Q3?"]}')
    assert summary == "A manual." and questions == ["Q1?", "Q2?", "Q3?"]
    with pytest.raises(ValueError):
        parse_reply("no json here")


# --- integration -----------------------------------------------------------------------------------------


class FakeModels:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.layout_reply: str | None = None  # reply to the "locate the text lines" prompt (None: not JSON)
        self.summary_reply = json.dumps(
            {
                "summary": "Firmware notes about the radio.",
                "questions": ["How is the channel set?", "What fails?"],
            }
        )

    async def aocr(self, model, document, **kwargs):
        self.calls.append(f"ocr:{model}")
        assert document["type"] == "image_url" and document["image_url"].startswith("data:image/jpeg;base64,")
        return SimpleNamespace(pages=[SimpleNamespace(markdown="FIRMWARE VERSION 4.2\n\nSerial ABC-123")])

    async def acompletion(self, model, messages, **kwargs):
        content = messages[0]["content"]
        if isinstance(content, list):
            prompt = content[0]["text"]
            kind = (
                "transcribe"
                if prompt.startswith("Transcribe")
                else "layout"
                if prompt.startswith("Locate")
                else "describe"
            )
            text = {
                "transcribe": "LABEL TEXT",
                "layout": self.layout_reply or "I can see a label.",
                "describe": "A photo of a router label with a serial number.",
            }[kind]
        else:
            kind, text = "summary", self.summary_reply
        self.calls.append(f"{kind}:{model}")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture
async def m3(client, admin_headers, session, embed_calls, jobs, monkeypatch):
    fake = FakeModels()
    monkeypatch.setattr(litellm, "aocr", fake.aocr)
    monkeypatch.setattr(litellm, "acompletion", fake.acompletion)

    async def catalog(kind, **_):
        return [
            DiscoveredModel("mistral-embed", capabilities={ModelPhase.embedding}, source="provider"),
            DiscoveredModel("mistral-ocr-latest", capabilities={ModelPhase.ocr}, source="provider"),
            DiscoveredModel(
                "pixtral-large", capabilities={ModelPhase.chat, ModelPhase.vision}, source="provider"
            ),
        ]

    monkeypatch.setattr(service, "list_models", catalog)
    models = await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "fw")
    notebook = await node(client, admin_headers, "notebook", "code", project["id"])
    other = await node(client, admin_headers, "notebook", "docs", project["id"])

    async def assign(phase: str, *names: str) -> None:
        r = await client.put(
            f"/api/model-assignments/{phase}",
            headers=admin_headers,
            json={"model_ids": [models[n] for n in names]},
        )
        assert r.status_code == 200, r.text

    return SimpleNamespace(fake=fake, models=models, project=project, nb=notebook, other=other, assign=assign)


async def sources_of(client, headers) -> dict[str, dict]:
    return {s["title"]: s for s in (await client.get("/api/sources", headers=headers)).json()}


async def test_archive_expands_into_child_sources(client, admin_headers, session, m3, jobs):
    inner = make_zip({"lib/util.py": b"def helper():\n    return 42\n"})
    archive = make_zip(
        {
            "src/radio.c": RADIO_C,
            "docs/README.md": b"# Firmware\n\nBuild with make and flash with the bootloader.\n",
            "assets/logo.png": make_png(),
            "bin/blob.bin": bytes(range(256)) * 4,
            "vendor/inner.zip": inner,
            "../escape.txt": b"no",
        }
    )
    [res] = await upload(client, admin_headers, m3.nb["id"], [("firmware.zip", archive)])
    assert res["source"]["kind"] == "archive"
    statuses = await run_jobs(session, jobs)  # archive, its children, the nested archive and its child
    assert statuses and all(s == SourceStatus.ready for s in statuses)

    by_title = await sources_of(client, admin_headers)
    root = by_title["firmware.zip"]
    details = root["details"]["archive"]
    assert details["files"] == 3 and details["format"] == "zip"
    reasons = {s["path"]: s["reason"] for s in details["skipped"]}
    assert reasons["../escape.txt"] == "unsafe path"
    assert "ARCHIVE_INDEX_IMAGES" in reasons["assets/logo.png"] and "Binary" in reasons["bin/blob.bin"]

    radio = by_title["src/radio.c"]
    assert radio["kind"] == "code" and radio["language"] == "c" and radio["parent_source_id"] == root["id"]
    assert by_title["vendor/inner.zip"]["kind"] == "archive"
    assert by_title["lib/util.py"]["parent_source_id"] == by_title["vendor/inner.zip"]["id"]
    chunks = (await client.get(f"/api/sources/{radio['id']}/chunks", headers=admin_headers)).json()
    func = next(c for c in chunks if c["heading_path"] == ["radio_set_channel"])
    assert func["line_start"] <= 3 and func["line_end"] == 10 and func["block_type"] == "code"
    text = (await client.get(f"/api/sources/{radio['id']}/text", headers=admin_headers)).text
    assert text == RADIO_C.decode()  # code keeps the original file text: lines match the file

    hits = await search(client, admin_headers, m3.project["id"], "radio set channel transmission")
    assert "src/radio.c" in {h["source_title"] for h in hits}
    manifest = await search(client, admin_headers, m3.nb["id"], "contents firmware.zip files src radio")
    assert "firmware.zip" in {h["source_title"] for h in manifest}
    # code and archive members get no summary
    assert radio["summary_status"] is None and by_title["docs/README.md"]["summary_status"] is None

    # switching the archive off switches its members off; deleting it deletes them
    await client.patch(f"/api/sources/{root['id']}", headers=admin_headers, json={"active": False})
    titles = {
        h["source_title"] for h in await search(client, admin_headers, m3.project["id"], "radio channel")
    }
    assert "src/radio.c" not in titles
    assert (await client.delete(f"/api/sources/{root['id']}", headers=admin_headers)).status_code == 204
    assert set(await sources_of(client, admin_headers)) == set()
    assert {j[0] for j in jobs} == {"purge"} and len(jobs) == 5  # archive, 3 members, nested member


async def test_malicious_archive_is_rejected_without_children(client, admin_headers, session, m3, jobs):
    bomb = make_zip({"zeros.bin": bytes(30 * 1024 * 1024)})
    await upload(client, admin_headers, m3.nb["id"], [("bomb.zip", bomb)])
    assert await run_jobs(session, jobs) == [SourceStatus.failed]
    [src] = (await sources_of(client, admin_headers)).values()
    assert src["error"]["code"] == "parse_error" and "zip bomb" in src["error"]["message"]


async def test_image_gets_ocr_and_description(client, admin_headers, session, m3, jobs):
    [res] = await upload(client, admin_headers, m3.nb["id"], [("label.png", make_png())])
    assert res["source"]["kind"] == "image"
    assert await run_jobs(session, jobs) == [SourceStatus.failed]
    src = (await sources_of(client, admin_headers))["label.png"]
    assert "OCR or a vision model" in src["error"]["message"]

    await m3.assign("ocr", "mistral-ocr-latest")
    await m3.assign("vision", "pixtral-large")
    await client.post(f"/api/sources/{src['id']}/reindex", headers=admin_headers)
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    assert m3.fake.calls[:2] == ["ocr:mistral/mistral-ocr-latest", "describe:mistral/pixtral-large"]
    chunks = (await client.get(f"/api/sources/{src['id']}/chunks", headers=admin_headers)).json()
    body = " ".join(c["text"] for c in chunks)
    assert "FIRMWARE VERSION 4.2" in body and "router label" in body
    hits = await search(client, admin_headers, m3.nb["id"], "serial ABC-123 firmware version")
    assert hits and hits[0]["source_title"] == "label.png"


async def test_scanned_pdf_pages_are_transcribed(client, admin_headers, session, m3, jobs):
    await m3.assign("vision", "pixtral-large")  # no OCR chain: the vision model transcribes
    await upload(client, admin_headers, m3.nb["id"], [("scan.pdf", make_scanned_pdf())])
    assert await run_jobs(session, jobs) == [SourceStatus.ready]
    src = (await sources_of(client, admin_headers))["scan.pdf"]
    assert any("OCR" in w for w in src["warnings"])
    chunks = (await client.get(f"/api/sources/{src['id']}/chunks", headers=admin_headers)).json()
    assert (
        chunks[0]["text"] == "LABEL TEXT"
        and chunks[0]["page_start"] == 1
        and chunks[0]["block_type"] == "ocr"
    )
    assert "transcribe:mistral/pixtral-large" in m3.fake.calls


async def test_summary_and_suggested_questions(client, admin_headers, session, m3, jobs):
    md = b"# Radio\n\nThe radio driver selects the channel and sets the transmit power before sending.\n"
    await upload(client, admin_headers, m3.nb["id"], [("radio.md", md)])
    await run_jobs(session, jobs)
    src = (await sources_of(client, admin_headers))["radio.md"]
    assert src["summary_status"] == "skipped"  # no summary model yet

    await m3.assign("summary", "pixtral-large")
    await client.post(f"/api/sources/{src['id']}/reindex", headers=admin_headers)
    await run_jobs(session, jobs)
    src = (await sources_of(client, admin_headers))["radio.md"]
    assert src["summary_status"] == "done" and src["summary"] == "Firmware notes about the radio."
    assert src["suggested_questions"] == ["How is the channel set?", "What fails?"]

    m3.fake.summary_reply = "I cannot do that."
    await client.post(f"/api/sources/{src['id']}/reindex", headers=admin_headers)
    await run_jobs(session, jobs)
    src = (await sources_of(client, admin_headers))["radio.md"]
    assert src["summary_status"] == "failed" and "Unreadable reply" in src["summary_error"]


PAGES = {
    "https://docs.example.com/": (
        "<html><head><title>Example Docs</title></head><body><nav>Menu</nav><main><h1>Welcome</h1>"
        "<p>The access point supports WPA3 and roaming between bands for every client device.</p>"
        "<p>Read the <a href='/install'>installation guide</a>, the <a href='/faq#top'>FAQ</a> and "
        "<a href='https://other.org/x'>another site</a>.</p></main><footer>Footer</footer></body></html>"
    ),
    "https://docs.example.com/install": (
        "<html><head><title>Installation</title></head><body><article><h1>Installation</h1>"
        "<p>Mount the access point on the ceiling and connect the PoE injector before powering on.</p>"
        "</article></body></html>"
    ),
    "https://docs.example.com/faq": (
        "<html><head><title>FAQ</title></head><body><article><h1>FAQ</h1>"
        "<p>Reset the device by holding the button for ten seconds until the light blinks.</p>"
        "</article></body></html>"
    ),
}


async def test_web_pages_with_bounded_crawl(client, admin_headers, session, m3, jobs, monkeypatch):
    fetched: list[str] = []

    async def fake_fetch(url, **_):
        fetched.append(url)
        return Fetched(url=url, content_type="text/html", data=PAGES[url].encode())

    async def allow(url):
        return url != "https://docs.example.com/faq"  # robots.txt disallows the FAQ

    monkeypatch.setattr(pipeline, "fetch", fake_fetch)
    monkeypatch.setattr(pipeline, "robots_allows", allow)
    r = await client.post(
        f"/api/nodes/{m3.other['id']}/web",
        headers=admin_headers,
        json={"urls": ["https://docs.example.com/#intro", "ftp://bad.example/"], "crawl_depth": 1},
    )
    assert r.status_code == 201, r.text
    ok, bad = r.json()
    assert ok["source"]["kind"] == "web" and ok["source"]["uri"] == "https://docs.example.com/"
    assert "http and https" in bad["error"]
    assert await run_jobs(session, jobs) == [SourceStatus.ready, SourceStatus.ready]
    assert fetched == ["https://docs.example.com/", "https://docs.example.com/install"]

    by_title = await sources_of(client, admin_headers)
    root, child = by_title["Example Docs"], by_title["Installation"]
    assert child["parent_source_id"] == root["id"] and root["details"]["crawl"]["links_followed"] == 1
    text = (await client.get(f"/api/sources/{root['id']}/text", headers=admin_headers)).text
    assert "WPA3" in text and "Menu" not in text and "Footer" not in text
    hits = await search(client, admin_headers, m3.other["id"], "mount ceiling PoE injector")
    assert hits[0]["source_title"] == "Installation"

    again = await client.post(
        f"/api/nodes/{m3.other['id']}/web", headers=admin_headers, json={"urls": ["https://docs.example.com"]}
    )
    assert again.json()[0]["duplicate"] is True
    too_deep = await client.post(
        f"/api/nodes/{m3.other['id']}/web",
        headers=admin_headers,
        json={"urls": ["https://x.example/"], "crawl_depth": 9},
    )
    assert too_deep.status_code == 422
