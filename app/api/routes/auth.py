from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_membership, get_current_user
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Organization, OrganizationMember, User
from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    OrganizationResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]) -> UserResponse:
    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo")

    settings = get_settings()
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )
    organization = Organization(
        name=payload.organization_name,
        max_profiles=settings.max_profiles_per_organization,
    )
    membership = OrganizationMember(user=user, organization=organization, role="owner")
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo")
    db.refresh(user)
    return _user_response(user, membership)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="La cuenta está desactivada")
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(
            str(user.id), settings.jwt_secret_key, settings.access_token_expire_minutes
        ),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def me(
    current_user: Annotated[User, Depends(get_current_user)],
    membership: Annotated[OrganizationMember, Depends(get_current_membership)],
) -> UserResponse:
    return _user_response(current_user, membership)


def _user_response(user: User, membership: OrganizationMember) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        organization=OrganizationResponse.model_validate(membership.organization),
        role=membership.role,
    )
