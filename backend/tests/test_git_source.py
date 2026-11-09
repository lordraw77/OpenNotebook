# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Git repository sources: policy, incremental sync, schedule, token handling.

The clone is replaced by a copy of a real local repository (git itself is exercised for commits); the git
command line, environment and URL policy are checked directly.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update

from opennotebook.config import get_settings
from opennotebook.ingestion import git as gitsrc
from opennotebook.models import Secret, Source, SourceStatus
from tests.test_sources import embed_calls, jobs, node, run_jobs, setup_embedding  # noqa: F401 - fixtures

URL = "http://gitlab.lan:8080/team/firmware"


def run(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - test helper, fixed arguments
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    path = tmp_path / "origin"
    path.mkdir()
    run(path, "init", "-q", "-b", "main")
    (path / "radio.c").write_text("int radio_set_channel(int c) { return c; }\n")
    (path / "README.md").write_text("# Firmware\n\nRadio firmware for the access point.\n")
    (path / "twin.md").write_text("# Firmware\n\nRadio firmware for the access point.\n")  # same content
    (path / "node_modules").mkdir()
    (path / "node_modules" / "x.js").write_text("module.exports = 1;\n")
    (path / "link").symlink_to("/etc/passwd")
    run(path, "add", "-A")
    run(path, "commit", "-q", "-m", "first")

    state = {"clones": 0, "token": None}
    monkeypatch.setattr(get_settings(), "git_allowed_hosts", "gitlab.lan:8080")

    async def remote_commit(url, branch, token, username):
        return run(path, "rev-parse", "HEAD")

    async def clone(url, branch, token, username):
        state["clones"] += 1
        state["token"] = token
        dest = Path(tempfile.mkdtemp(prefix="repo-test-"))
        shutil.copytree(path, dest / "work", symlinks=True, ignore=shutil.ignore_patterns(".git"))
        return gitsrc.Checkout(path=dest / "work", commit=run(path, "rev-parse", "HEAD"), branch="main")

    monkeypatch.setattr(gitsrc, "remote_commit", remote_commit)
    monkeypatch.setattr(gitsrc, "clone", clone)
    return type("Repo", (), {"path": path, "state": state, "run": staticmethod(run)})


async def children(session, root_id):
    await session.rollback()  # fresh view
    rows = await session.scalars(
        select(Source).where(Source.parent_source_id == root_id, Source.deleted_at.is_(None))
    )
    return {s.metadata_["git_path"]: SimpleNamespace(id=s.id, status=s.status) for s in rows.all()}


async def add_repo(client, headers, notebook, **extra):
    r = await client.post(
        f"/api/nodes/{notebook['id']}/git", headers=headers, json={"url": URL, "branch": "main", **extra}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_url_policy(monkeypatch):
    monkeypatch.setattr(get_settings(), "git_allowed_hosts", "")
    with pytest.raises(gitsrc.GitError, match="off"):
        gitsrc.validate_url(URL)
    monkeypatch.setattr(get_settings(), "git_allowed_hosts", "gitlab.lan:8080, github.com")
    assert gitsrc.validate_url("http://GitLab.lan:8080/team/firmware/") == URL
    assert gitsrc.validate_url("https://github.com/a/b") == "https://github.com/a/b"
    for bad, text in [
        ("ssh://gitlab.lan:8080/team/f", "http"),
        ("file:///etc", "http"),
        ("http://gitlab.lan:9090/team/f", "GIT_ALLOWED_HOSTS"),
        ("http://evil.example/team/f", "GIT_ALLOWED_HOSTS"),
        ("http://user:pw@gitlab.lan:8080/team/f", "token"),
        ("http://gitlab.lan:8080/", "path"),
    ]:
        with pytest.raises(gitsrc.GitError, match=text):
            gitsrc.validate_url(bad)
    assert gitsrc.validate_branch("feature/x-1") == "feature/x-1"
    for bad in ["--upload-pack=x", "a..b", "-x", "a b", "x.lock"]:
        with pytest.raises(gitsrc.GitError):
            gitsrc.validate_branch(bad)


def test_git_environment_keeps_the_token_out_of_the_command_line():
    env = gitsrc._env("/tmp/h", "s3cret", "bob")
    assert "s3cret" not in " ".join(env.values())  # only its base64 form travels, in a header
    header = next(
        v for k, v in env.items() if k.startswith("GIT_CONFIG_VALUE") and v.startswith("Authorization")
    )
    import base64

    assert base64.b64decode(header.split()[-1]).decode() == "bob:s3cret"
    assert env["GIT_ALLOW_PROTOCOL"] == "http:https" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert gitsrc._scrub("fatal: bad s3cret", "s3cret") == "fatal: bad ***"


async def test_add_repository_needs_the_allow_list(client, admin_headers, monkeypatch):
    project = await node(client, admin_headers, "project", "fw")
    monkeypatch.setattr(get_settings(), "git_allowed_hosts", "")
    r = await client.post(f"/api/nodes/{project['id']}/git", headers=admin_headers, json={"url": URL})
    assert r.status_code == 422 and "GIT_ALLOWED_HOSTS" in r.json()["detail"]


async def test_sync_is_incremental(client, admin_headers, session, embed_calls, jobs, repo):
    await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "fw")
    root = await add_repo(client, admin_headers, project, token="glpat-secret", sync_interval_minutes=30)
    assert root["details"]["git"]["token_set"] is True and "glpat-secret" not in str(root)
    assert (
        await client.post(
            f"/api/nodes/{project['id']}/git", headers=admin_headers, json={"url": URL, "branch": "main"}
        )
    ).status_code == 409
    await run_jobs(session, jobs)
    assert repo.state["token"] == "glpat-secret"

    first = await children(session, uuid(root["id"]))
    assert set(first) == {"radio.c", "README.md"}  # node_modules, the symlink and the duplicate are left out
    detail = (await client.get(f"/api/sources/{root['id']}", headers=admin_headers)).json()
    git = detail["details"]["git"]
    assert (
        git["added"] == 2 and git["files"] == 2 and git["commit"] == repo.run(repo.path, "rev-parse", "HEAD")
    )
    reasons = {s["path"]: s["reason"] for s in git["skipped"]}
    assert "link" in reasons and "twin.md" in reasons
    assert detail["status"] == "ready" and first["radio.c"].status == SourceStatus.ready

    # same commit: the remote is asked, nothing is cloned
    clones = repo.state["clones"]
    assert (await client.post(f"/api/sources/{root['id']}/sync", headers=admin_headers)).status_code == 200
    await run_jobs(session, jobs)
    assert repo.state["clones"] == clones

    # a change, a removal and an addition
    (repo.path / "radio.c").write_text("int radio_set_channel(int c) { return c + 1; }\n")
    (repo.path / "README.md").unlink()
    (repo.path / "src").mkdir()
    (repo.path / "src" / "wifi.py").write_text("def connect():\n    return True\n")
    repo.run(repo.path, "add", "-A")
    repo.run(repo.path, "commit", "-q", "-m", "second")
    (await client.post(f"/api/sources/{root['id']}/sync", headers=admin_headers)).raise_for_status()
    await run_jobs(session, jobs)
    second = await children(session, uuid(root["id"]))
    assert set(second) == {"radio.c", "src/wifi.py", "twin.md"}  # twin.md is no longer a duplicate
    assert second["radio.c"].id != first["radio.c"].id  # replaced, re-indexed
    git = (await client.get(f"/api/sources/{root['id']}", headers=admin_headers)).json()["details"]["git"]
    assert (git["added"], git["changed"], git["removed"]) == (2, 1, 1)

    # unchanged files keep their index across another commit
    (repo.path / "notes.txt").write_text("remember the radio\n")
    repo.run(repo.path, "add", "-A")
    repo.run(repo.path, "commit", "-q", "-m", "third")
    (await client.post(f"/api/sources/{root['id']}/sync", headers=admin_headers)).raise_for_status()
    await run_jobs(session, jobs)
    third = await children(session, uuid(root["id"]))
    assert third["radio.c"].id == second["radio.c"].id and "notes.txt" in third


async def test_schedule_and_settings(client, admin_headers, session, embed_calls, jobs, repo):
    await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "fw")
    manual = await add_repo(client, admin_headers, project, sync_interval_minutes=0)
    await run_jobs(session, jobs)

    # a manual-only repository is never queued; a scheduled one only when its interval has passed
    assert await gitsrc.enqueue_due(session, datetime.now(UTC) + timedelta(days=30)) == 0
    r = await client.patch(
        f"/api/sources/{manual['id']}/git",
        headers=admin_headers,
        json={"sync_interval_minutes": 15, "exclude": ["*.md"], "token": "t1"},
    )
    assert r.status_code == 200 and r.json()["details"]["git"]["sync_interval_minutes"] == 15
    assert await gitsrc.enqueue_due(session, datetime.now(UTC) + timedelta(minutes=5)) == 0
    assert await gitsrc.enqueue_due(session, datetime.now(UTC) + timedelta(minutes=16)) == 1
    assert [j[2] for j in jobs] == ["schedule"]
    assert await gitsrc.enqueue_due(session, datetime.now(UTC) + timedelta(minutes=16)) == 0  # already queued
    await run_jobs(session, jobs)
    # the exclude filter changed, so the files were looked at again even at the same commit
    assert set(await children(session, uuid(manual["id"]))) == {"radio.c"}

    # replacing and removing the token
    secrets = await session.scalar(select(func.count()).select_from(Secret))
    (
        await client.patch(f"/api/sources/{manual['id']}/git", headers=admin_headers, json={"token": ""})
    ).raise_for_status()
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(Secret)) == secrets - 1
    await session.execute(
        update(Source).where(Source.id == uuid(manual["id"])).values(status=SourceStatus.ready)
    )


async def test_sync_requires_a_git_source(client, admin_headers, session, embed_calls, jobs, repo):
    await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "fw")
    from tests.test_sources import upload

    [res] = await upload(client, admin_headers, project["id"], [("a.md", b"# a\n\nhello world\n")])
    r = await client.post(f"/api/sources/{res['source']['id']}/sync", headers=admin_headers)
    assert r.status_code == 409


def uuid(value):
    import uuid as _uuid

    return _uuid.UUID(value)
