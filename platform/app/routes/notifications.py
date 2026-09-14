"""Internal callback routes — invoked by user containers (not by browsers).

Currently hosts the cron completion notification endpoint: after a cron job
finishes inside a user container, the scheduler POSTs here with the container
token; the platform resolves the owning user and emails them (best-effort).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_db
from app.db.models import Container, User
from app.mail_service import notify_cron_completed

logger = logging.getLogger("platform.routes.notifications")
router = APIRouter(prefix="/api/internal", tags=["internal"])


class CronNotifyBody(BaseModel):
    job_name: str = ""
    session_key: str = ""
    success: bool = True
    result_text: str = ""


def _container_token_from_request(request: Request) -> str:
    token = request.headers.get("X-Container-Token", "").strip()
    if not token:
        authorization = request.headers.get("Authorization", "").strip()
        if authorization.startswith("Bearer "):
            token = authorization[7:].strip()
    return token


@router.post("/cron-notify")
async def cron_notify(
    body: CronNotifyBody,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Cron job completion callback from a user container → email the owner."""
    token = _container_token_from_request(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing container token")

    row = (
        await db.execute(select(Container).where(Container.container_token == token))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown container token")

    user = (
        await db.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    user_email = user.email if user else ""

    session_url = settings.public_base_url.rstrip("/") + "/agents/grzs/"
    if body.session_key:
        session_url += "chat?session=" + quote(body.session_key, safe="")

    job_name = body.job_name or "定时任务"
    background_tasks.add_task(
        notify_cron_completed, user_email, job_name, session_url, body.success, body.result_text
    )
    logger.info(
        "cron_notify accepted user=%s job=%s success=%s",
        row.user_id,
        job_name,
        body.success,
    )
    return {"ok": True}
