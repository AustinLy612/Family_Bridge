"""Authentication: login/logout, session, code redemption, password reset/change (Plan §5.1)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AppSettings, AuthPrincipal, Db, OptionalPrincipal
from app.api.schemas import (
    CodeIn,
    CodeInfo,
    LoginIn,
    PasswordChangeIn,
    RedeemIn,
    ResetIn,
    SessionOut,
    UserOut,
)
from app.core import audit
from app.core.errors import ApiError, bad_request, conflict, unauthorized
from app.core.security import (
    code_limiter,
    hash_password,
    login_limiter,
    needs_rehash,
    new_pseudonym,
    normalise_username,
    password_problems,
    username_valid,
    verify_password,
)
from app.core.sessions import (
    clear_session_cookie,
    create_session,
    revoke_all_sessions,
    set_session_cookie,
    utcnow,
)
from app.models import (
    PARTICIPANT_ROLES,
    AuthSession,
    CodePurpose,
    FamilyMember,
    Invitation,
    Role,
    User,
    UserStatus,
)
from app.research import events as research_events
from app.services import codes
from app.settings import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int) -> ApiError:
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS, "auth.too_many_attempts", retry_after=retry_after
    )


def _check_code_rate(request: Request) -> None:
    settings: Settings = request.app.state.settings
    window = settings.code_ip_window_seconds
    if not code_limiter.hit(
        "code:" + _client_ip(request), limit=settings.code_ip_max_attempts, window_seconds=window
    ):
        raise _too_many(window)


def _lockout_seconds(failures: int, settings: Settings) -> int:
    over = failures - settings.login_max_failures
    return int(
        min(settings.login_lockout_base_seconds * (2**over), settings.login_lockout_max_seconds)
    )


def _login_event(db: Db, kind: str, user: User | None) -> None:
    research_events.record(db, kind, user)


def _session_out(user: User, sess: AuthSession) -> SessionOut:
    return SessionOut(user=UserOut.of(user), csrf_token=sess.csrf_token)


def _start_session(db: Db, response: Response, user: User, settings: Settings) -> SessionOut:
    token, sess = create_session(db, user, settings)
    set_session_cookie(response, token, settings)
    return _session_out(user, sess)


def _check_password(password: str, username: str) -> None:
    problems = password_problems(password, username=username)
    if problems:
        raise bad_request("password.invalid", problems=problems)


@router.get("/session")
def get_session(principal: OptionalPrincipal) -> SessionOut:
    if principal is None:
        return SessionOut(user=None)
    return _session_out(principal.user, principal.session)


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> SessionOut:
    if not login_limiter.hit(
        "ip:" + _client_ip(request),
        limit=settings.login_ip_max_attempts,
        window_seconds=settings.login_ip_window_seconds,
    ):
        raise _too_many(settings.login_ip_window_seconds)

    username = normalise_username(body.username)
    user = db.execute(
        select(User).where(func.lower(User.username) == username).with_for_update()
    ).scalar_one_or_none()
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        verify_password(None, body.password)  # keep timing similar
        audit.record(db, "auth.login_locked", actor=user, target_type="user", target_id=user.id)
        _login_event(db, "login_failure", user)
        db.commit()
        raise _too_many(int((user.locked_until - now).total_seconds()) + 1)

    ok = verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None or user.status is not UserStatus.active:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= settings.login_max_failures:
                user.locked_until = now + timedelta(
                    seconds=_lockout_seconds(user.failed_logins, settings)
                )
        audit.record(
            db,
            "auth.login_failed",
            actor=user,
            target_type="user" if user else None,
            target_id=user.id if user else None,
            details={"reason": "disabled" if ok and user else "bad_credentials"},
        )
        _login_event(db, "login_failure", user)
        db.commit()
        raise unauthorized("auth.invalid_credentials")

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    audit.record(db, "auth.login", actor=user, target_type="user", target_id=user.id)
    _login_event(db, "login_success", user)
    return _start_session(db, response, user, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: AuthPrincipal, response: Response, db: Db, settings: AppSettings) -> None:
    principal.session.revoked_at = utcnow()
    audit.record(
        db, "auth.logout", actor=principal.user, target_type="user", target_id=principal.user.id
    )
    clear_session_cookie(response, settings)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(principal: AuthPrincipal, response: Response, db: Db, settings: AppSettings) -> None:
    revoke_all_sessions(db, principal.user.id)
    audit.record(
        db, "auth.logout_all", actor=principal.user, target_type="user", target_id=principal.user.id
    )
    clear_session_cookie(response, settings)


@router.post("/codes/inspect")
def inspect_code(body: CodeIn, request: Request, db: Db) -> CodeInfo:
    _check_code_rate(request)
    inv = codes.find_usable(db, body.code)
    username = None
    if inv.purpose is CodePurpose.reset and inv.target_user_id is not None:
        target = db.get(User, inv.target_user_id)
        username = target.username if target else None
    return CodeInfo(
        purpose=inv.purpose.value,
        role=inv.intended_role,
        expires_at=inv.expires_at,
        username=username,
    )


@router.post("/redeem")
def redeem(
    body: RedeemIn, request: Request, response: Response, db: Db, settings: AppSettings
) -> SessionOut:
    """Turn an invitation code into an account (alias, language, password), then sign in.

    Participants still have to complete onboarding consent before they can use the app.
    """
    _check_code_rate(request)
    inv = codes.find_usable(db, body.code, CodePurpose.invite)

    username = normalise_username(body.username)
    if not username_valid(username):
        raise bad_request("username.invalid")
    _check_password(body.password, username)
    if db.execute(select(User.id).where(func.lower(User.username) == username)).first():
        raise conflict("username.taken")

    role = inv.intended_role
    if role in PARTICIPANT_ROLES:
        if inv.family_id is None:
            raise bad_request("code.invalid")
        if role is Role.adolescent and _family_has_adolescent(db, inv):
            raise conflict("family.adolescent_exists")

    now = utcnow()
    user = User(
        pseudonym_code=new_pseudonym(),
        username=username,
        role=role,
        display_alias=body.display_alias.strip(),
        language=body.language,
        a11y_prefs={},
        password_hash=hash_password(body.password),
        status=UserStatus.active,
        is_demo=_invite_is_demo(db, inv),
        failed_logins=0,
        last_login_at=now,
        # Staff accounts have no participant consent flow (Plan §5.2 applies to participants).
        onboarded_at=None if role in PARTICIPANT_ROLES else now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent registration of the same username
        db.rollback()
        raise conflict("username.taken") from exc

    if role in PARTICIPANT_ROLES:
        db.add(
            FamilyMember(
                family_id=inv.family_id,
                user_id=user.id,
                member_role=role,
                relationship_label=inv.relationship_label,
            )
        )
    inv.used_at = now
    research_events.record(db, "enrolment.code_redeemed", user, purpose=inv.purpose.value)
    inv.used_by = user.id
    audit.record(
        db,
        "invitation.redeemed",
        actor=user,
        target_type="invitation",
        target_id=inv.id,
        details={"role": role.value, "family_id": str(inv.family_id) if inv.family_id else None},
    )
    _login_event(db, "login_success", user)
    return _start_session(db, response, user, settings)


def _family_has_adolescent(db: Db, inv: Invitation) -> bool:
    return (
        db.execute(
            select(FamilyMember.id).where(
                FamilyMember.family_id == inv.family_id, FamilyMember.member_role == Role.adolescent
            )
        ).first()
        is not None
    )


def _invite_is_demo(db: Db, inv: Invitation) -> bool:
    creator = db.get(User, inv.created_by)
    return bool(creator and creator.is_demo)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: ResetIn, request: Request, db: Db) -> None:
    """Set a new password with a staff-issued reset code (D30). Signs the account out everywhere."""
    _check_code_rate(request)
    inv = codes.find_usable(db, body.code, CodePurpose.reset)
    user = db.get(User, inv.target_user_id) if inv.target_user_id else None
    if user is None:
        raise bad_request("code.invalid")
    _check_password(body.password, user.username)
    now = utcnow()
    user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    inv.used_at = now
    research_events.record(db, "enrolment.code_redeemed", user, purpose=inv.purpose.value)
    inv.used_by = user.id
    revoke_all_sessions(db, user.id)
    audit.record(db, "auth.password_reset", actor=user, target_type="invitation", target_id=inv.id)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeIn, principal: AuthPrincipal, db: Db) -> None:
    user = principal.user
    if not verify_password(user.password_hash, body.current_password):
        raise bad_request("password.current_wrong")
    _check_password(body.new_password, user.username)
    user.password_hash = hash_password(body.new_password)
    # Keep this session, sign out every other one.
    for other in db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.id != principal.session.id,
        )
    ).scalars():
        other.revoked_at = utcnow()
    audit.record(db, "auth.password_changed", actor=user, target_type="user", target_id=user.id)
