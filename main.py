import json
import logging
import os
import uuid
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Generator

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saas_gbp.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError("La variable de entorno JWT_SECRET_KEY es obligatoria")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
MAX_FICHAS_PER_USER = 5
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY")
GOOGLE_OAUTH_SCOPE = (
    "openid email https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/business.manage"
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("saas_gbp")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    fichas = relationship("FichaGBP", back_populates="owner")
    google_connections = relationship(
        "GoogleConnection", back_populates="user", cascade="all, delete-orphan"
    )


class GoogleConnection(Base):
    __tablename__ = "google_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    email = Column(String(320), nullable=False)
    encrypted_refresh_token = Column(Text, nullable=False)
    scopes = Column(Text, nullable=True)
    fecha_conexion = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_actualizacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="google_connections")


class FichaGBP(Base):
    __tablename__ = "fichas_gbp"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    google_connection_id = Column(Integer, ForeignKey("google_accounts.id"), nullable=True, index=True)
    nombre_negocio = Column(String(255), nullable=False)
    categoria = Column(String(255), nullable=False)
    ciudad = Column(String(255), nullable=False)
    gemini_api_key = Column(String(255), nullable=False)
    prompt_custom = Column(Text, nullable=True)
    gbp_auth_token = Column(Text, nullable=True)
    google_account_name = Column(String(255), nullable=True)
    google_location_name = Column(String(255), nullable=True)
    direccion = Column(Text, nullable=True)
    telefono = Column(String(100), nullable=True)
    sitio_web = Column(Text, nullable=True)
    google_data = Column(Text, nullable=True)
    fecha_sincronizacion = Column(DateTime, nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="fichas")
    posts = relationship("PostRecord", back_populates="ficha", cascade="all, delete-orphan")
    reviews = relationship("ReviewRecord", back_populates="ficha", cascade="all, delete-orphan")


class PostRecord(Base):
    __tablename__ = "historial_posts"

    id = Column(Integer, primary_key=True, index=True)
    ficha_id = Column(Integer, ForeignKey("fichas_gbp.id"), nullable=False)
    keywords = Column(String(255))
    post_1_text = Column(Text)
    post_2_text = Column(Text)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    ficha = relationship("FichaGBP", back_populates="posts")


class ReviewRecord(Base):
    __tablename__ = "reviews_gbp"

    id = Column(Integer, primary_key=True)
    ficha_id = Column(Integer, ForeignKey("fichas_gbp.id"), nullable=False, index=True)
    google_review_id = Column(String(255), nullable=False)
    reviewer_name = Column(String(255), nullable=True)
    star_rating = Column(String(30), nullable=True)
    comment = Column(Text, nullable=True)
    review_reply = Column(Text, nullable=True)
    create_time = Column(DateTime(timezone=True), nullable=True)
    update_time = Column(DateTime(timezone=True), nullable=True)

    ficha = relationship("FichaGBP", back_populates="reviews")


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    fecha_creacion: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class FichaCreate(BaseModel):
    nombre_negocio: str = Field(min_length=1, max_length=255)
    categoria: str = Field(min_length=1, max_length=255)
    ciudad: str = Field(min_length=1, max_length=255)
    gemini_api_key: str = Field(min_length=1, max_length=255)
    prompt_custom: str | None = None
    gbp_auth_token: str | None = None


class FichaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_negocio: str
    categoria: str
    ciudad: str
    prompt_custom: str | None
    tiene_gemini_api_key: bool
    tiene_gbp_auth_token: bool
    google_conectada: bool
    direccion: str | None
    telefono: str | None
    sitio_web: str | None
    fecha_sincronizacion: datetime | None
    fecha_creacion: datetime


class GoogleConnectionStatus(BaseModel):
    connected: bool
    accounts: list["GoogleAccountResponse"] = Field(default_factory=list)


class GoogleAccountResponse(BaseModel):
    id: int
    email: str
    fecha_conexion: datetime


class GoogleLocationCandidate(BaseModel):
    account_name: str
    location_name: str
    title: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    category: str | None = None


class GoogleImportRequest(BaseModel):
    connection_id: int
    locations: list[GoogleLocationCandidate] = Field(min_length=1, max_length=5)
    gemini_api_key: str = Field(min_length=1, max_length=255)
    prompt_custom: str | None = None


class ArticleRequest(BaseModel):
    article_content: str = Field(min_length=1)
    target_keywords: str = Field(min_length=1, max_length=255)


class GBPPost(BaseModel):
    post_type: str
    post_text: str
    call_to_action_type: str
    suggested_cta_url: str


class GBPPostsResponse(BaseModel):
    post_1: GBPPost
    post_2: GBPPost


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expires}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def require_google_settings() -> None:
    missing = [
        name
        for name, value in {
            "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
            "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
            "GOOGLE_REDIRECT_URI": GOOGLE_REDIRECT_URI,
            "TOKEN_ENCRYPTION_KEY": TOKEN_ENCRYPTION_KEY,
        }.items()
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"Faltan variables de Google en el servidor: {', '.join(missing)}",
        )


def token_cipher() -> Fernet:
    require_google_settings()
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode())
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=503, detail="TOKEN_ENCRYPTION_KEY no es una clave Fernet válida"
        ) from exc


def google_access_token(connection: GoogleConnection) -> str:
    try:
        refresh_token = token_cipher().decrypt(
            connection.encrypted_refresh_token.encode()
        ).decode()
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="No se pudo descifrar la conexión Google") from exc

    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Google no pudo renovar la autorización; vuelve a conectar la cuenta",
        ) from exc


def google_get(url: str, access_token: str, params: dict | None = None) -> dict:
    try:
        response = httpx.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-GOOG-API-FORMAT-VERSION": "2",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("error", {}).get("message", exc.response.text)
        raise HTTPException(status_code=502, detail=f"Google Business Profile: {detail}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="No se pudo consultar Google Business Profile") from exc


def public_error_detail(exc: Exception) -> str:
    """Keep provider errors useful without leaking tokens or request bodies."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return exc.response.json().get("error", {}).get("message") or exc.response.text[:300]
        except ValueError:
            return exc.response.text[:300]
    return str(exc)[:300]


def format_address(address: dict | None) -> str | None:
    if not address:
        return None
    parts = [
        *address.get("addressLines", []),
        address.get("postalCode"),
        address.get("locality"),
        address.get("administrativeArea"),
        address.get("regionCode"),
    ]
    return ", ".join(str(part) for part in parts if part)


def candidate_from_google(account_name: str, location: dict) -> GoogleLocationCandidate:
    categories = location.get("categories", {})
    primary = categories.get("primaryCategory", {})
    phones = location.get("phoneNumbers", {})
    return GoogleLocationCandidate(
        account_name=account_name,
        location_name=location["name"],
        title=location.get("title", "Negocio sin nombre"),
        address=format_address(location.get("storefrontAddress")),
        phone=phones.get("primaryPhone"),
        website=location.get("websiteUri"),
        category=primary.get("displayName"),
    )


def fetch_google_locations(access_token: str) -> list[GoogleLocationCandidate]:
    accounts_data = google_get(
        "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
        access_token,
    )
    candidates: list[GoogleLocationCandidate] = []
    for account in accounts_data.get("accounts", []):
        account_name = account.get("name")
        if not account_name:
            continue
        page_token = None
        while True:
            params = {
                "readMask": (
                    "name,title,storefrontAddress,phoneNumbers,categories,"
                    "websiteUri,regularHours,metadata,profile"
                ),
                "pageSize": 100,
            }
            if page_token:
                params["pageToken"] = page_token
            data = google_get(
                f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations",
                access_token,
                params,
            )
            candidates.extend(
                candidate_from_google(account_name, location)
                for location in data.get("locations", [])
            )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return candidates


def parse_google_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def sync_reviews(db: Session, ficha: FichaGBP, access_token: str) -> None:
    parent = f"{ficha.google_account_name}/{ficha.google_location_name}"
    page_token = None
    while True:
        params = {"pageSize": 50}
        if page_token:
            params["pageToken"] = page_token
        data = google_get(
            f"https://mybusiness.googleapis.com/v4/{parent}/reviews",
            access_token,
            params,
        )
        for review in data.get("reviews", []):
            review_id = review.get("reviewId")
            if not review_id:
                continue
            record = (
                db.query(ReviewRecord)
                .filter(
                    ReviewRecord.ficha_id == ficha.id,
                    ReviewRecord.google_review_id == review_id,
                )
                .first()
            )
            if not record:
                record = ReviewRecord(ficha_id=ficha.id, google_review_id=review_id)
                db.add(record)
            record.reviewer_name = review.get("reviewer", {}).get("displayName")
            record.star_rating = review.get("starRating")
            record.comment = review.get("comment")
            record.review_reply = review.get("reviewReply", {}).get("comment")
            record.create_time = parse_google_datetime(review.get("createTime"))
            record.update_time = parse_google_datetime(review.get("updateTime"))
        page_token = data.get("nextPageToken")
        if not page_token:
            break


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o caducado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", ""))
    except (JWTError, TypeError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)
    if not user:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def serialize_ficha(ficha: FichaGBP) -> FichaResponse:
    return FichaResponse(
        id=ficha.id,
        nombre_negocio=ficha.nombre_negocio,
        categoria=ficha.categoria,
        ciudad=ficha.ciudad,
        prompt_custom=ficha.prompt_custom,
        tiene_gemini_api_key=bool(ficha.gemini_api_key),
        tiene_gbp_auth_token=bool(ficha.gbp_auth_token),
        google_conectada=bool(ficha.google_location_name),
        direccion=ficha.direccion,
        telefono=ficha.telefono,
        sitio_web=ficha.sitio_web,
        fecha_sincronizacion=ficha.fecha_sincronizacion,
        fecha_creacion=ficha.fecha_creacion,
    )


app = FastAPI(title="SaaS GBP API Multitenant", version="0.2.0")


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    error_id = uuid.uuid4().hex[:10]
    logger.exception(
        "error_id=%s method=%s path=%s",
        error_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno (referencia {error_id})"},
    )


@app.on_event("startup")
def create_tables() -> None:
    tables_before = set(inspect(engine).get_table_names())
    Base.metadata.create_all(bind=engine)
    # Compatibilidad con la tabla creada por la primera versión del prototipo.
    # Las fichas antiguas quedan sin propietario y no se exponen a ningún usuario.
    inspector = inspect(engine)
    if "fichas_gbp" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("fichas_gbp")}
        legacy_columns = {
            "owner_id": "INTEGER REFERENCES users(id)",
            "google_connection_id": "INTEGER REFERENCES google_accounts(id)",
            "google_account_name": "VARCHAR(255)",
            "google_location_name": "VARCHAR(255)",
            "direccion": "TEXT",
            "telefono": "VARCHAR(100)",
            "sitio_web": "TEXT",
            "google_data": "TEXT",
            "fecha_sincronizacion": "TIMESTAMP",
        }
        with engine.begin() as connection:
            for column_name, column_type in legacy_columns.items():
                if column_name in columns:
                    continue
                connection.execute(
                    text(
                        f"ALTER TABLE fichas_gbp ADD COLUMN {column_name} {column_type}"
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fichas_gbp_owner_id "
                    "ON fichas_gbp (owner_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fichas_gbp_google_location "
                    "ON fichas_gbp (owner_id, google_location_name)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fichas_gbp_google_connection_id "
                    "ON fichas_gbp (google_connection_id)"
                )
            )
    # Migra la conexión única de versiones anteriores al modelo multi-cuenta.
    if "google_connections" in tables_before and "google_accounts" not in tables_before:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO google_accounts "
                    "(user_id, email, encrypted_refresh_token, scopes, fecha_conexion, fecha_actualizacion) "
                    "SELECT old.user_id, users.email, old.encrypted_refresh_token, old.scopes, "
                    "old.fecha_conexion, old.fecha_actualizacion "
                    "FROM google_connections old JOIN users ON users.id = old.user_id "
                    "WHERE NOT EXISTS (SELECT 1 FROM google_accounts fresh "
                    "WHERE fresh.user_id = old.user_id AND fresh.email = users.email)"
                )
            )
            connection.execute(
                text(
                    "UPDATE fichas_gbp SET google_connection_id = "
                    "(SELECT id FROM google_accounts WHERE google_accounts.user_id = fichas_gbp.owner_id "
                    "ORDER BY id LIMIT 1) "
                    "WHERE google_connection_id IS NULL AND owner_id IS NOT NULL"
                )
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_google_accounts_user_email "
                "ON google_accounts (user_id, email)"
            )
        )


@app.post("/api/v1/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: UserRegister, db: DbSession):
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con este email")

    user = User(email=email, password_hash=password_context.hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: UserLogin, db: DbSession):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not password_context.verify(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/api/v1/auth/me", response_model=UserResponse)
def me(current_user: CurrentUser):
    return current_user


@app.get("/api/v1/google/status", response_model=GoogleConnectionStatus)
def google_status(db: DbSession, current_user: CurrentUser):
    connections = (
        db.query(GoogleConnection)
        .filter(GoogleConnection.user_id == current_user.id)
        .order_by(GoogleConnection.fecha_conexion)
        .all()
    )
    return GoogleConnectionStatus(
        connected=bool(connections),
        accounts=[
            GoogleAccountResponse(
                id=item.id, email=item.email, fecha_conexion=item.fecha_conexion
            )
            for item in connections
        ],
    )


@app.get("/api/v1/google/connect")
def google_connect(current_user: CurrentUser):
    require_google_settings()
    oauth_state = jwt.encode(
        {
            "sub": str(current_user.id),
            "purpose": "google_oauth",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )
    query = urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": GOOGLE_OAUTH_SCOPE,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": oauth_state,
        }
    )
    return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}"}


@app.get("/api/v1/google/callback")
def google_callback(
    db: DbSession,
    code: str | None = Query(default=None),
    state_token: str | None = Query(default=None, alias="state"),
    error: str | None = Query(default=None),
):
    if error:
        return RedirectResponse(url=f"/?google=error&reason={error}")
    if not code or not state_token:
        raise HTTPException(status_code=400, detail="Respuesta OAuth incompleta")
    require_google_settings()
    try:
        state_payload = jwt.decode(
            state_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM]
        )
        if state_payload.get("purpose") != "google_oauth":
            raise JWTError("Propósito incorrecto")
        user_id = int(state_payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido o caducado") from exc

    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI,
            },
            timeout=20,
        )
        response.raise_for_status()
        token_data = response.json()
        profile_response = httpx.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            timeout=20,
        )
        profile_response.raise_for_status()
        google_email = profile_response.json()["email"].lower()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        error_id = uuid.uuid4().hex[:10]
        logger.exception("error_id=%s Google OAuth failed", error_id)
        raise HTTPException(
            status_code=502,
            detail=f"Google no pudo completar OAuth: {public_error_detail(exc)} "
            f"(referencia {error_id})",
        ) from exc

    refresh_token = token_data.get("refresh_token")
    connection = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.user_id == user_id,
            GoogleConnection.email == google_email,
        )
        .first()
    )
    if not refresh_token and not connection:
        raise HTTPException(
            status_code=400,
            detail="Google no entregó refresh_token; revoca el acceso y vuelve a conectar",
        )
    if not connection:
        connection = GoogleConnection(
            user_id=user_id, email=google_email, encrypted_refresh_token=""
        )
        db.add(connection)
    if refresh_token:
        connection.encrypted_refresh_token = (
            token_cipher().encrypt(refresh_token.encode()).decode()
        )
    connection.scopes = token_data.get("scope")
    connection.fecha_actualizacion = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/?google=connected")


def get_google_connection(
    db: Session, user_id: int, connection_id: int
) -> GoogleConnection:
    connection = (
        db.query(GoogleConnection)
        .filter(
            GoogleConnection.id == connection_id,
            GoogleConnection.user_id == user_id,
        )
        .first()
    )
    if not connection:
        raise HTTPException(status_code=409, detail="Primero debes conectar una cuenta Google")
    return connection


@app.get("/api/v1/google/locations", response_model=list[GoogleLocationCandidate])
def google_locations(connection_id: int, db: DbSession, current_user: CurrentUser):
    connection = get_google_connection(db, current_user.id, connection_id)
    return fetch_google_locations(google_access_token(connection))


@app.delete("/api/v1/google/connections/{connection_id}", status_code=204)
def delete_google_connection(
    connection_id: int, db: DbSession, current_user: CurrentUser
):
    connection = get_google_connection(db, current_user.id, connection_id)
    db.query(FichaGBP).filter(
        FichaGBP.owner_id == current_user.id,
        FichaGBP.google_connection_id == connection.id,
    ).update({FichaGBP.google_connection_id: None}, synchronize_session=False)
    db.delete(connection)
    db.commit()
    return Response(status_code=204)


@app.post("/api/v1/google/import", response_model=list[FichaResponse], status_code=201)
def import_google_locations(
    payload: GoogleImportRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    connection = get_google_connection(db, current_user.id, payload.connection_id)
    access_token = google_access_token(connection)
    available = {
        (candidate.account_name, candidate.location_name): candidate
        for candidate in fetch_google_locations(access_token)
    }
    requested_keys = {
        (candidate.account_name, candidate.location_name)
        for candidate in payload.locations
    }
    if len(requested_keys) != len(payload.locations):
        raise HTTPException(status_code=422, detail="Hay ubicaciones duplicadas")
    if not requested_keys.issubset(available):
        raise HTTPException(
            status_code=403,
            detail="Una ubicación no pertenece a la cuenta Google conectada",
        )

    existing = (
        db.query(FichaGBP)
        .filter(FichaGBP.owner_id == current_user.id)
        .all()
    )
    existing_keys = {
        (ficha.google_account_name, ficha.google_location_name)
        for ficha in existing
        if ficha.google_location_name and ficha.google_connection_id == connection.id
    }
    new_keys = requested_keys - existing_keys
    if len(existing) + len(new_keys) > MAX_FICHAS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"La importación supera el límite de {MAX_FICHAS_PER_USER} fichas",
        )

    imported: list[FichaGBP] = []
    try:
        for key in requested_keys:
            candidate = available[key]
            ficha = next(
                (
                    item
                    for item in existing
                    if item.google_connection_id == connection.id
                    and (item.google_account_name, item.google_location_name) == key
                ),
                None,
            )
            if not ficha:
                ficha = FichaGBP(
                    owner_id=current_user.id,
                    nombre_negocio=candidate.title,
                    categoria=candidate.category or "Sin categoría",
                    ciudad=candidate.address or "Sin ubicación",
                    gemini_api_key=payload.gemini_api_key,
                    google_account_name=candidate.account_name,
                    google_location_name=candidate.location_name,
                    google_connection_id=connection.id,
                )
                db.add(ficha)
                db.flush()
            ficha.nombre_negocio = candidate.title
            ficha.google_connection_id = connection.id
            ficha.categoria = candidate.category or ficha.categoria
            ficha.direccion = candidate.address
            ficha.telefono = candidate.phone
            ficha.sitio_web = candidate.website
            ficha.gemini_api_key = payload.gemini_api_key
            ficha.prompt_custom = payload.prompt_custom
            ficha.google_data = candidate.model_dump_json()
            ficha.fecha_sincronizacion = datetime.utcnow()
            sync_reviews(db, ficha, access_token)
            imported.append(ficha)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        error_id = uuid.uuid4().hex[:10]
        logger.exception("error_id=%s import failed user_id=%s", error_id, current_user.id)
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo completar la importación: {public_error_detail(exc)} "
            f"(referencia {error_id})",
        ) from exc

    for ficha in imported:
        db.refresh(ficha)
    return [serialize_ficha(ficha) for ficha in imported]


@app.get("/api/v1/fichas", response_model=list[FichaResponse])
def listar_fichas(db: DbSession, current_user: CurrentUser):
    fichas = (
        db.query(FichaGBP)
        .filter(FichaGBP.owner_id == current_user.id)
        .order_by(FichaGBP.fecha_creacion.desc())
        .all()
    )
    return [serialize_ficha(ficha) for ficha in fichas]


@app.delete("/api/v1/fichas/{ficha_id}", status_code=204)
def borrar_ficha(ficha_id: int, db: DbSession, current_user: CurrentUser):
    ficha = (
        db.query(FichaGBP)
        .filter(FichaGBP.id == ficha_id, FichaGBP.owner_id == current_user.id)
        .first()
    )
    if not ficha:
        raise HTTPException(status_code=404, detail="Ficha GBP no encontrada")
    try:
        # El borrado explícito funciona también con bases antiguas cuyas claves
        # foráneas no se crearon con ON DELETE CASCADE.
        db.query(PostRecord).filter(PostRecord.ficha_id == ficha.id).delete(
            synchronize_session=False
        )
        db.query(ReviewRecord).filter(ReviewRecord.ficha_id == ficha.id).delete(
            synchronize_session=False
        )
        db.delete(ficha)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return Response(status_code=204)


@app.post(
    "/api/v1/fichas/{ficha_id}/generate-posts",
    response_model=GBPPostsResponse,
)
def generate_posts_para_ficha(
    ficha_id: int,
    request: ArticleRequest,
    db: DbSession,
    current_user: CurrentUser,
):
    ficha = (
        db.query(FichaGBP)
        .filter(FichaGBP.id == ficha_id, FichaGBP.owner_id == current_user.id)
        .first()
    )
    if not ficha:
        raise HTTPException(status_code=404, detail="Ficha GBP no encontrada")

    prompt_base = ficha.prompt_custom or (
        "Eres un experto en SEO Local y copywriting para Google Business Profile. "
        "Crea EXACTAMENTE 2 publicaciones enfocadas en la conversión local."
    )
    prompt_final = f"""
{prompt_base}

Contexto del negocio:
- Nombre: {ficha.nombre_negocio}
- Categoría: {ficha.categoria}
- Ciudad: {ficha.ciudad}

Palabras clave objetivo: {request.target_keywords}
Contenido del artículo base:
{request.article_content}
"""

    try:
        client = genai.Client(api_key=ficha.gemini_api_key)
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt_final,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GBPPostsResponse,
            ),
        )
        result_json = json.loads(response.text)
        result = GBPPostsResponse.model_validate(result_json)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini no pudo generar las publicaciones: {exc}",
        ) from exc

    try:
        db.add(
            PostRecord(
                ficha_id=ficha.id,
                keywords=request.target_keywords,
                post_1_text=result.post_1.post_text,
                post_2_text=result.post_2.post_text,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="No se pudo guardar el historial") from exc

    return result


static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
