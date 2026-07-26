import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Generator

from fastapi import Depends, FastAPI, HTTPException, status
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

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    fichas = relationship("FichaGBP", back_populates="owner")


class FichaGBP(Base):
    __tablename__ = "fichas_gbp"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    nombre_negocio = Column(String(255), nullable=False)
    categoria = Column(String(255), nullable=False)
    ciudad = Column(String(255), nullable=False)
    gemini_api_key = Column(String(255), nullable=False)
    prompt_custom = Column(Text, nullable=True)
    gbp_auth_token = Column(Text, nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    owner = relationship("User", back_populates="fichas")
    posts = relationship("PostRecord", back_populates="ficha", cascade="all, delete-orphan")


class PostRecord(Base):
    __tablename__ = "historial_posts"

    id = Column(Integer, primary_key=True, index=True)
    ficha_id = Column(Integer, ForeignKey("fichas_gbp.id"), nullable=False)
    keywords = Column(String(255))
    post_1_text = Column(Text)
    post_2_text = Column(Text)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    ficha = relationship("FichaGBP", back_populates="posts")


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
    fecha_creacion: datetime


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
        fecha_creacion=ficha.fecha_creacion,
    )


app = FastAPI(title="SaaS GBP API Multitenant", version="0.2.0")


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    # Compatibilidad con la tabla creada por la primera versión del prototipo.
    # Las fichas antiguas quedan sin propietario y no se exponen a ningún usuario.
    inspector = inspect(engine)
    if "fichas_gbp" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("fichas_gbp")}
        if "owner_id" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE fichas_gbp "
                        "ADD COLUMN owner_id INTEGER REFERENCES users(id)"
                    )
                )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_fichas_gbp_owner_id "
                    "ON fichas_gbp (owner_id)"
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


@app.post("/api/v1/fichas", response_model=FichaResponse, status_code=201)
def crear_ficha(ficha: FichaCreate, db: DbSession, current_user: CurrentUser):
    total = db.query(FichaGBP).filter(FichaGBP.owner_id == current_user.id).count()
    if total >= MAX_FICHAS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Has alcanzado el límite de {MAX_FICHAS_PER_USER} fichas",
        )

    nueva_ficha = FichaGBP(owner_id=current_user.id, **ficha.model_dump())
    db.add(nueva_ficha)
    db.commit()
    db.refresh(nueva_ficha)
    return serialize_ficha(nueva_ficha)


@app.get("/api/v1/fichas", response_model=list[FichaResponse])
def listar_fichas(db: DbSession, current_user: CurrentUser):
    fichas = (
        db.query(FichaGBP)
        .filter(FichaGBP.owner_id == current_user.id)
        .order_by(FichaGBP.fecha_creacion.desc())
        .all()
    )
    return [serialize_ficha(ficha) for ficha in fichas]


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
