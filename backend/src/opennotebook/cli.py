"""Command line entry point: `opennotebook <command>`.

Commands:
  api        run the HTTP API (uvicorn)
  worker     run a Celery worker (pass extra Celery args after --)
  migrate    apply database migrations
  bootstrap  create the first admin, ensure the storage bucket, import providers/model defaults from env
  reset-admin  create the administrator or reset its password (BOOTSTRAP_ADMIN_* or --email/--password)
  doctor     check connectivity to every internal service and configured provider
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("opennotebook.cli")


def _alembic_config():  # type: ignore[no-untyped-def]
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    return cfg


def cmd_migrate(_: argparse.Namespace) -> int:
    from alembic import command

    command.upgrade(_alembic_config(), "head")
    print("migrations applied")
    return 0


async def _bootstrap(sync: bool) -> dict:
    from sqlalchemy import func, select

    from opennotebook.config import get_settings
    from opennotebook.db import get_sessionmaker
    from opennotebook.models import Provider, User
    from opennotebook.providers.catalog import ProviderError
    from opennotebook.providers.service import (
        import_assignments_from_env,
        import_providers_from_env,
        sync_models,
    )
    from opennotebook.security import hash_password
    from opennotebook.storage import get_blob_store

    settings = get_settings()
    report: dict = {}
    await get_blob_store().ensure_ready()
    report["storage"] = "ready"
    async with get_sessionmaker()() as session:
        users = await session.scalar(select(func.count()).select_from(User))
        if not users:
            if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
                session.add(
                    User(
                        email=settings.bootstrap_admin_email.lower(),
                        display_name="Administrator",
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        is_admin=True,
                    )
                )
                await session.commit()
                report["admin"] = f"created {settings.bootstrap_admin_email}"
            else:
                report["admin"] = "no users and BOOTSTRAP_ADMIN_EMAIL/PASSWORD not set"
        else:
            report["admin"] = "users exist, skipped"

        report["providers_imported"] = await import_providers_from_env(session)
        if sync:
            synced = {}
            for provider in (
                await session.scalars(select(Provider).where(Provider.last_sync_at.is_(None)))
            ).all():
                try:
                    synced[provider.name] = await sync_models(session, provider)
                except ProviderError as exc:
                    synced[provider.name] = f"error: {exc}"
                except Exception as exc:  # noqa: BLE001 - one provider must not block the first start
                    await session.rollback()
                    log.exception("model sync failed for %s", provider.name)
                    synced[provider.name] = f"error: {exc.__class__.__name__}"
            report["providers_synced"] = synced
        report["model_defaults"] = await import_assignments_from_env(session)
    return report


def cmd_bootstrap(args: argparse.Namespace) -> int:
    print(json.dumps(asyncio.run(_bootstrap(sync=not args.no_sync)), indent=2))
    return 0


async def _doctor() -> dict:
    import httpx
    from sqlalchemy import select

    from opennotebook.api.health import check_components
    from opennotebook.db import get_sessionmaker
    from opennotebook.models import Provider
    from opennotebook.providers.catalog import ProviderError, list_models
    from opennotebook.providers.gateway import decrypt_provider_key

    report: dict = {"components": await check_components(), "providers": {}}
    async with get_sessionmaker()() as session, httpx.AsyncClient(timeout=30) as client:
        for p in (await session.scalars(select(Provider).where(Provider.enabled.is_(True)))).all():
            try:
                models = await list_models(
                    p.kind,
                    api_key=await decrypt_provider_key(session, p),
                    base_url=p.base_url,
                    options=p.options or {},
                    client=client,
                )
                report["providers"][p.name] = {"ok": True, "models": len(models)}
            except ProviderError as exc:
                report["providers"][p.name] = {"ok": False, "error": str(exc)}
    return report


def cmd_doctor(_: argparse.Namespace) -> int:
    report = asyncio.run(_doctor())
    print(json.dumps(report, indent=2))
    ok = all(c["ok"] for c in report["components"]) and all(p["ok"] for p in report["providers"].values())
    return 0 if ok else 1


async def reset_admin(email: str, password: str) -> str:
    """Create the administrator, or reset its password, admin role and active state; revoke its sessions."""
    from sqlalchemy import delete, select

    from opennotebook.db import get_sessionmaker
    from opennotebook.models import AuditLog, RefreshToken, User
    from opennotebook.security import hash_password

    email = email.strip().lower()
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == email))
        action = "reset"
        if user is None:
            user = User(email=email, display_name="Administrator", password_hash="", is_admin=True)
            session.add(user)
            action = "created"
        user.password_hash = hash_password(password)
        user.is_admin = True
        user.is_active = True
        await session.flush()
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
        session.add(
            AuditLog(actor_id=None, action=f"admin.{action}", target_type="user", target_id=str(user.id))
        )
        await session.commit()
    return action


def cmd_reset_admin(args: argparse.Namespace) -> int:
    from opennotebook.config import get_settings

    settings = get_settings()
    email = args.email or settings.bootstrap_admin_email
    password = args.password or os.environ.get("RESET_ADMIN_PASSWORD") or settings.bootstrap_admin_password
    if not email or not password:
        print("Set --email/--password or BOOTSTRAP_ADMIN_EMAIL/BOOTSTRAP_ADMIN_PASSWORD", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("The password must be at least 12 characters", file=sys.stderr)
        return 2
    action = asyncio.run(reset_admin(email, password))
    print(f"administrator {action}: {email.lower()} (existing sessions revoked)")
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "opennotebook.main:app",
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
        log_config=None,
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from opennotebook.worker import QUEUES, celery_app

    argv = ["worker", "--loglevel=INFO", f"--queues={','.join(QUEUES)}", *args.celery_args]
    celery_app.worker_main(argv)
    return 0


def main(argv: list[str] | None = None) -> int:
    from opennotebook.config import get_settings
    from opennotebook.logging_setup import configure_logging

    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="opennotebook")
    sub = parser.add_subparsers(dest="command", required=True)

    p_api = sub.add_parser("api", help="run the HTTP API")
    p_api.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container entrypoint
    p_api.add_argument("--port", type=int, default=8000)
    p_api.set_defaults(func=cmd_api)

    p_worker = sub.add_parser("worker", help="run a Celery worker")
    p_worker.add_argument("celery_args", nargs=argparse.REMAINDER)
    p_worker.set_defaults(func=cmd_worker)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    p_boot = sub.add_parser("bootstrap", help="first-start initialization (idempotent)")
    p_boot.add_argument("--no-sync", action="store_true", help="do not sync provider model catalogs")
    p_boot.set_defaults(func=cmd_bootstrap)
    sub.add_parser("doctor", help="connectivity checks").set_defaults(func=cmd_doctor)
    p_reset = sub.add_parser(
        "reset-admin",
        help="create the administrator or reset its password (defaults: BOOTSTRAP_ADMIN_EMAIL/PASSWORD)",
    )
    p_reset.add_argument("--email")
    p_reset.add_argument(
        "--password", help="prefer RESET_ADMIN_PASSWORD or BOOTSTRAP_ADMIN_PASSWORD (not shell history)"
    )
    p_reset.set_defaults(func=cmd_reset_admin)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
