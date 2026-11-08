#!/usr/bin/env python3
"""Create or update the Docker Hub repositories of OpenNotebook and their overview (full description).

Credentials: DOCKERHUB_USERNAME + DOCKERHUB_TOKEN (password or personal access token with read/write scope),
or the Docker Hub entry of ~/.docker/config.json written by `docker login`. They are never printed.

Usage: scripts/dockerhub_repos.py <namespace> <version>
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://hub.docker.com/v2"
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "dockerhub"

IMAGES = {
    "opennotebook-web": ("web", "Web UI", "OpenNotebook web UI (Angular + nginx): self-hosted RAG workspace with grounded, cited chat"),
    "opennotebook-api": ("api", "API", "OpenNotebook API (FastAPI): grounded RAG chat, knowledge graph, multi-provider model gateway"),
    "opennotebook-worker": ("worker", "Ingestion worker", "OpenNotebook ingestion worker: parsing, OCR, web, embeddings, knowledge graph, summaries"),
}


def credentials() -> tuple[str, str]:
    user, secret = os.environ.get("DOCKERHUB_USERNAME"), os.environ.get("DOCKERHUB_TOKEN")
    if user and secret:
        return user, secret
    config = json.loads((Path.home() / ".docker" / "config.json").read_text())
    auth = config.get("auths", {}).get("https://index.docker.io/v1/", {}).get("auth")
    if not auth:
        sys.exit("No Docker Hub credentials: set DOCKERHUB_USERNAME/DOCKERHUB_TOKEN or run `docker login`")
    user, _, secret = base64.b64decode(auth).decode().partition(":")
    return user, secret


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "opennotebook-release")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"detail": raw[:200].decode(errors="replace")}


def overview(key: str, title: str, version: str) -> str:
    text = (DOCS / "overview.md").read_text()
    text = text.replace("{{TITLE}}", title)
    text = text.replace("{{ROLE}}", (DOCS / f"{key}.md").read_text().strip())
    text = text.replace("{{IMAGE_DETAILS}}", (DOCS / f"{key}-details.md").read_text().strip())
    return text


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    namespace, version = sys.argv[1], sys.argv[2]
    user, secret = credentials()
    status, login = call("POST", "/users/login", body={"username": user, "password": secret})
    token = login.get("token")
    if status != 200 or not token:
        sys.exit(f"Docker Hub login failed (HTTP {status}): {login.get('detail') or login.get('message')}")
    for name, (key, title, short) in IMAGES.items():
        full = overview(key, title, version)
        body = {"description": short[:100], "full_description": full}
        status, repo = call("GET", f"/repositories/{namespace}/{name}/", token)
        if status == 404:
            status, repo = call(
                "POST",
                "/repositories/",
                token,
                {"namespace": namespace, "name": name, "is_private": False, **body},
            )
            action = "created"
        else:
            status, repo = call("PATCH", f"/repositories/{namespace}/{name}/", token, body)
            action = "updated"
        if status not in (200, 201):
            sys.exit(f"{namespace}/{name}: HTTP {status} {repo.get('detail') or repo.get('message') or repo}")
        print(f"{namespace}/{name}: {action} (public={not repo.get('is_private')}, overview {len(full)} chars)")


if __name__ == "__main__":
    main()
