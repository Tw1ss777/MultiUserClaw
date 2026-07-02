"""Authentication API routes."""

from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException, status
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.auth.service import (
    AuthFailureReason,
    authenticate_user_with_reason,
    create_access_token,
    create_api_token,
    create_refresh_token,
    create_user,
    decode_token,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    hash_password,
    verify_password,
)
from app.audit import write_audit_log
from app.config import settings
from app.auth.dependencies import get_current_user
from app.db.engine import get_db
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    runtime_mode: str | None = None


class LoginRequest(BaseModel):
    username: str  # accepts username or email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str


class RefreshRequest(BaseModel):
    refresh_token: str

class SSOLoginRequest(BaseModel):
    infox_token: str
    runtime_mode: str | None = None


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    quota_tier: str
    runtime_mode: str
    is_active: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if await get_user_by_username(db, req.username):
        raise HTTPException(status_code=400, detail="账号已存在")
    if await get_user_by_email(db, req.email):
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    user = await create_user(db, req.username, req.email, req.password)
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user, failure_reason = await authenticate_user_with_reason(db, req.username, req.password)
    if user is None:
        detail = "登录失败"
        if failure_reason == AuthFailureReason.USER_NOT_FOUND:
            detail = "账号不存在"
        elif failure_reason == AuthFailureReason.ACCOUNT_DISABLED:
            detail = "账号已被禁用"
        elif failure_reason == AuthFailureReason.PASSWORD_INCORRECT:
            detail = "密码错误"
        await write_audit_log(
            db,
            action="login_failed",
            resource=req.username,
            detail={"reason": failure_reason or "unknown"},
            commit=True,
        )
        raise HTTPException(status_code=401, detail=detail)
    await write_audit_log(
        db,
        action="login",
        user_id=user.id,
        resource=user.username,
        detail={"role": user.role},
        commit=True,
    )
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

@router.post("/sso", response_model=TokenResponse)
async def sso_login(req: SSOLoginRequest, db: AsyncSession = Depends(get_db)):
    if not settings.aihub_base_url:
        raise HTTPException(status_code=400, detail="SSO not configured (AIHUB_BASE_URL)")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.aihub_base_url}/auth/verify",
                json={"token": req.infox_token},
                timeout=10.0,
            )
        body = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"SSO verification request failed: ai-hub may be unreachable ({e})",
        )
    # ai-hub TransformInterceptor wraps responses as {code:0, data: {...}, message:"ok"}
    payload = body.get("data", body) if isinstance(body, dict) else body
    if not (200 <= resp.status_code < 300) or not isinstance(payload, dict) or not payload.get("valid"):
        reason = payload.get("reason", "unknown") if isinstance(payload, dict) else "invalid response"
        raise HTTPException(status_code=401, detail=f"SSO token invalid: {reason}")
    user_info = payload["user"]
    sso_username = (user_info.get("username") or "").strip()
    if not sso_username:
        raise HTTPException(status_code=400, detail="No username from SSO provider")
    sso_email = f"{sso_username}@test.com"
    aihub_roles = user_info.get("roles") or []
    sso_role = "admin" if isinstance(aihub_roles, list) and "ADMIN" in aihub_roles else "user"
    print(f"[sso] user={sso_username} aihub_roles={aihub_roles} sso_role={sso_role}")
    litellm_key = user_info.get("litellmApiKey")
    user = await get_user_by_username(db, sso_username)
    if user is None:
        import secrets

        random_pw = secrets.token_urlsafe(24)
        base_username = sso_username
        try:
            user = User(
                username=base_username,
                email=sso_email,
                password_hash=hash_password(random_pw),
                sso_uid=user_info.get("id"),
                sso_token=req.infox_token,
                litellm_api_key=litellm_key,
                role=sso_role,
                runtime_mode=req.runtime_mode or "dedicated",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            # Username conflict → append random suffix
            base_username = f"{base_username}_{secrets.token_hex(4)}"
            user = User(
                username=base_username,
                email=sso_email,
                password_hash=hash_password(random_pw),
                sso_uid=user_info.get("id"),
                sso_token=req.infox_token,
                litellm_api_key=litellm_key,
                role=sso_role,
                runtime_mode=req.runtime_mode or "dedicated",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
    else:
        if litellm_key:
            user.litellm_api_key = litellm_key
        user.role = sso_role
        await db.commit()


    await write_audit_log(
        db,
        action="sso_login",
        user_id=user.id,
        resource=user.username,
        detail={"provider": "aihub"},
        commit=True,
    )
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = await get_user_by_id(db, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        quota_tier=user.quota_tier,
        runtime_mode=user.runtime_mode,
        is_active=user.is_active,
    )


class ApiTokenResponse(BaseModel):
    api_token: str
    expires_in_days: int = 365


@router.post("/api-token", response_model=ApiTokenResponse)
async def generate_api_token(user: User = Depends(get_current_user)):
    """Generate a long-lived API token for programmatic access."""
    token = create_api_token(user.id, user.role)
    return ApiTokenResponse(api_token=token)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.put("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少需要6个字符")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "密码修改成功"}
