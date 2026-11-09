"""Git repository sources: clone over HTTP(S) into a temporary directory and read the working tree.

A repository is a source of its own (an archive-like root); its files become child sources that keep the
repository path. Re-syncing compares the remote commit and then each file's hash, so only added, changed and
removed files cost embedding work. Safety:

- only `http` and `https`, no credentials in the URL, and the host must be listed in `GIT_ALLOWED_HOSTS`
  (empty = the feature is off): git connects by itself, so the allow-list replaces the web fetcher's address
  checks and lets an intranet GitLab be reached without opening the private network to everything;
- no hooks, no submodules, no symlinks (never followed or read), no redirects, no prompts, no system or user
  git configuration, a time limit, and a size and file-count limit on what is read;
- the access token travels in the process environment as an HTTP header, never in the command line, and is
  removed from any error text.
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from opennotebook.config import get_settings
from opennotebook.ingestion.parsers import ParseError

DEFAULT_EXCLUDE = (
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".idea",
    ".vscode",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.lock",
    "package-lock.json",
)
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]{0,199}$")


class GitError(ParseError):
    """The repository cannot be used (policy, authentication, missing branch); not retryable."""


class GitTransient(Exception):
    """Network problem worth retrying (timeout, connection refused, server error)."""


def allowed_hosts() -> set[str]:
    return {h.strip().lower() for h in get_settings().git_allowed_hosts.split(",") if h.strip()}


def validate_url(raw: str) -> str:
    """The URL in the form stored and used: http(s), no credentials, host (and port) on the allow-list."""
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in ("http", "https"):
        raise GitError("Only http and https repository URLs are supported")
    if not parts.hostname:
        raise GitError("The URL has no host")
    if parts.username or parts.password:
        raise GitError("Put the access token in the token field, not in the URL")
    hosts = allowed_hosts()
    if not hosts:
        raise GitError("Git sources are off: set GIT_ALLOWED_HOSTS to the hosts that may be cloned")
    host = parts.hostname.lower()
    hostport = f"{host}:{parts.port}" if parts.port else host
    if host not in hosts and hostport not in hosts:
        raise GitError(f"Host '{hostport}' is not in GIT_ALLOWED_HOSTS")
    path = parts.path.rstrip("/")
    if not path or path == "/":
        raise GitError("The URL has no repository path")
    netloc = hostport
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def validate_branch(branch: str | None) -> str | None:
    if not branch:
        return None
    if not _BRANCH.match(branch) or ".." in branch or branch.endswith(("/", ".lock")):
        raise GitError("Invalid branch name")
    return branch


def digest(url: str, branch: str | None) -> bytes:
    """Repositories are unique per notebook, url and branch."""
    return hashlib.sha256(f"git:{url}#{branch or ''}".encode()).digest()


def _env(home: str, token: str | None, username: str | None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "LANG": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "http:https",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_LFS_SKIP_SMUDGE": "1",
    }
    settings = [
        ("http.followRedirects", "false"),
        ("core.hooksPath", "/dev/null"),
        ("core.symlinks", "false"),
        ("protocol.version", "2"),
        ("http.lowSpeedLimit", "1000"),
        ("http.lowSpeedTime", "60"),
    ]
    if token:
        basic = base64.b64encode(f"{username or 'oauth2'}:{token}".encode()).decode()
        settings.append(("http.extraHeader", f"Authorization: Basic {basic}"))
    env["GIT_CONFIG_COUNT"] = str(len(settings))
    for i, (key, value) in enumerate(settings):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def _scrub(text: str, token: str | None) -> str:
    if token:
        text = text.replace(token, "***")
    return text.strip()[-400:]


async def _git(args: list[str], *, token: str | None, username: str | None, cwd: str | None = None) -> str:
    timeout = get_settings().git_timeout_seconds
    with tempfile.TemporaryDirectory(prefix="git-home-") as home:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=cwd,
                env=_env(home, token, username),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitError("git is not installed in this image") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise GitTransient(f"git timed out after {timeout} s") from exc
    if proc.returncode != 0:
        message = _scrub(err.decode("utf-8", "replace"), token)
        lowered = message.lower()
        if any(
            s in lowered for s in ("authentication failed", "could not read username", "401", "403", "denied")
        ):
            raise GitError(f"Authentication failed or access denied: {message}")
        if any(s in lowered for s in ("not found", "404", "does not exist", "couldn't find remote ref")):
            raise GitError(f"Repository or branch not found: {message}")
        if any(
            s in lowered for s in ("could not resolve", "connection", "timed out", "502", "503", "504", "500")
        ):
            raise GitTransient(message)
        raise GitError(f"git failed: {message}")
    return out.decode("utf-8", "replace")


async def remote_commit(url: str, branch: str | None, token: str | None, username: str | None) -> str:
    """The commit the branch (or the default branch) points to now, without cloning."""
    ref = f"refs/heads/{branch}" if branch else "HEAD"
    out = await _git(["ls-remote", "--", url, ref], token=token, username=username)
    for line in out.splitlines():
        sha = line.split("\t", 1)[0].strip()
        if re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return sha
    raise GitError(f"Branch '{branch}' not found" if branch else "The repository has no commits")


@dataclass
class Checkout:
    path: Path
    commit: str
    branch: str | None


async def clone(url: str, branch: str | None, token: str | None, username: str | None) -> Checkout:
    """Shallow clone of one branch into a new temporary directory (the caller removes it)."""
    dest = Path(tempfile.mkdtemp(prefix="repo-"))
    try:
        args = ["clone", "--depth", "1", "--single-branch", "--no-tags", "--no-recurse-submodules", "--quiet"]
        if branch:
            args += ["--branch", branch]
        args += ["--", url, str(dest / "work")]
        await _git(args, token=token, username=username)
        work = dest / "work"
        commit = (await _git(["rev-parse", "HEAD"], token=None, username=None, cwd=str(work))).strip()
        name = (
            await _git(["rev-parse", "--abbrev-ref", "HEAD"], token=None, username=None, cwd=str(work))
        ).strip()
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return Checkout(path=work, commit=commit, branch=branch or name)


def discard(checkout: Checkout) -> None:
    shutil.rmtree(checkout.path.parent, ignore_errors=True)


def _excluded(path: str, patterns: tuple[str, ...]) -> bool:
    parts = path.split("/")
    for pattern in patterns:
        if "/" in pattern:
            if fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("/") + "/"):
                return True
        elif any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


@dataclass
class TreeFile:
    path: str
    size: int
    sha256: bytes


def walk(
    root: Path, exclude: list[str], include: list[str], max_files: int, max_file_bytes: int
) -> tuple[list[TreeFile], list[dict]]:
    """Regular files of the working tree with their hash; symlinks and special files are never read."""
    patterns = (*DEFAULT_EXCLUDE, *exclude)
    files: list[TreeFile] = []
    skipped: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        dirnames[:] = sorted(d for d in dirnames if not _excluded(f"{rel_dir}/{d}".lstrip("/"), patterns))
        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}".lstrip("/")
            full = Path(dirpath) / name
            if _excluded(rel, patterns):
                continue
            if include and not any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in include):
                continue
            if full.is_symlink() or not full.is_file():
                skipped.append({"path": rel, "reason": "symbolic link or special file"})
                continue
            size = full.stat().st_size
            if size > max_file_bytes:
                skipped.append({"path": rel, "reason": "larger than UPLOAD_MAX_MB"})
                continue
            if len(files) >= max_files:
                skipped.append({"path": rel, "reason": "more than GIT_MAX_FILES files"})
                continue
            files.append(TreeFile(rel, size, hashlib.sha256(full.read_bytes()).digest()))
    return files, skipped


def read(root: Path, path: str) -> bytes:
    full = (root / path).resolve()
    if (
        root.resolve() not in full.parents
    ):  # defence in depth: paths come from walk(), but never leave the tree
        raise GitError("Path outside the repository")
    return full.read_bytes()


def tree_size(files: list[TreeFile]) -> int:
    return sum(f.size for f in files)


def iter_paths(files: list[TreeFile]) -> Iterator[str]:
    yield from (f.path for f in files)


async def enqueue_due(session, now: datetime | None = None) -> int:  # type: ignore[no-untyped-def]
    """Queue a sync for every repository whose schedule is due; safe to run on several workers at once."""
    from sqlalchemy import select

    from opennotebook.ingestion import queue
    from opennotebook.models import Source, SourceKind, SourceStatus

    now = now or datetime.now(UTC)
    rows = (
        await session.scalars(
            select(Source)
            .where(
                Source.kind == SourceKind.archive,
                Source.deleted_at.is_(None),
                Source.status.in_((SourceStatus.ready, SourceStatus.failed)),
                Source.metadata_["git"].is_not(None),
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    queued: list = []
    for source in rows:
        minutes = int(((source.metadata_ or {}).get("git") or {}).get("sync_interval_minutes") or 0)
        if minutes > 0 and source.updated_at + timedelta(minutes=minutes) <= now:
            source.status = SourceStatus.queued
            source.error = None
            queued.append(source.id)
    await session.commit()
    for source_id in queued:
        queue.enqueue_ingestion(source_id, "schedule")
    return len(queued)
