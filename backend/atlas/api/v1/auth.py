"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from atlas.api.cookies import clear_session_cookies, set_session_cookies
from atlas.api.deps import AuthServiceDep, ClientInfoDep, CurrentUser, GuardDep, SettingsDep
from atlas.core.errors import UnauthenticatedError
from atlas.core.security import REFRESH_COOKIE_NAME
from atlas.schemas.auth import LoginRequest, RegisterRequest, SessionResponse, UserRead
from atlas.security import policy

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    client: ClientInfoDep,
    guard: GuardDep,
) -> SessionResponse:
    await guard.by_address(request, policy.REGISTRATION_PER_ADDRESS, scope="register")
    session = await auth.register(
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        client=client,
    )
    set_session_cookies(response, session, settings)
    return SessionResponse(
        user=UserRead.model_validate(session.user),
        access_token_expires_at=session.access_token_expires_at,
    )


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    client: ClientInfoDep,
    guard: GuardDep,
) -> SessionResponse:
    # Two limits, because either one alone is bypassable. Per-account stops an attacker
    # guessing one password from many addresses; per-address stops one host spraying attempts
    # across many accounts. Both are checked before the password is verified, so a rejected
    # attempt costs no argon2 hashing — which is also what keeps this from being a way to
    # exhaust CPU on purpose.
    await guard.by_identifier(payload.email, policy.LOGIN_PER_ACCOUNT, scope="login")
    await guard.by_address(request, policy.LOGIN_PER_ADDRESS, scope="login")

    session = await auth.login(email=payload.email, password=payload.password, client=client)

    # A correct password clears the account's counter, so a person who mistypes several times
    # and then succeeds is not left throttled.
    await guard.clear_identifier(payload.email, scope="login")
    set_session_cookies(response, session, settings)
    return SessionResponse(
        user=UserRead.model_validate(session.user),
        access_token_expires_at=session.access_token_expires_at,
    )


@router.post("/refresh", response_model=SessionResponse)
async def refresh(
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
    client: ClientInfoDep,
    guard: GuardDep,
) -> SessionResponse:
    await guard.by_address(request, policy.REFRESH_PER_ADDRESS, scope="refresh")
    token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not token:
        raise UnauthenticatedError(detail="no refresh cookie present")

    session = await auth.refresh(refresh_token=token, client=client)
    set_session_cookies(response, session, settings)
    return SessionResponse(
        user=UserRead.model_validate(session.user),
        access_token_expires_at=session.access_token_expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    await auth.revoke(refresh_token=request.cookies.get(REFRESH_COOKIE_NAME))
    # Cookies are set on the injected response, whose headers FastAPI merges into the 204.
    clear_session_cookies(response, settings)


@router.get("/me", response_model=UserRead)
async def read_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
