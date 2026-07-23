import os
import json
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from google import genai
from google.genai import types
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

# --- 1. CONEXIÓN A POSTGRESQL ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 2. MODELOS DE TABLAS (SQLAlchemy) ---

class FichaGBP(Base):
    __tablename__ = "fichas_gbp"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre_negocio = Column(String(255), nullable=False)
    categoria = Column(String(255))
    ciudad = Column(String(255))
    
    # Credenciales y configuración independiente por Ficha
    gemini_api_key = Column(String(255), nullable=False) # API Key propia del cliente
    prompt_custom = Column(Text, nullable=True)          # Prompt personalizado de esta ficha
    gbp_auth_token = Column(Text, nullable=True)         # Token OAuth futuro para conectar a Google
    
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    
    # Relación con sus posts
    posts = relationship("PostRecord", back_populates="ficha", cascade="all, delete-orphan")

class PostRecord(Base):
    __tablename__ = "historial_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    ficha_id = Column(Integer, ForeignKey("fichas_gbp.id"), nullable=False)
    keywords = Column(String(255))
    post_1_text = Column(Text)
    post_2_text = Column(Text)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    
    ficha = relationship("FichaGBP", back_populates="posts")

Base.metadata.create_all(bind=engine)

# --- 3. ESQUEMAS DATO ENTRADA/SALIDA (Pydantic) ---

class FichaCreate(BaseModel):
    nombre_negocio: str
    categoria: str
    ciudad: str
    gemini_api_key: str
    prompt_custom: Optional[str] = None
    gbp_auth_token: Optional[str] = None

class ArticleRequest(BaseModel):
    article_content: str
    target_keywords: str

class GBPPost(BaseModel):
    post_type: str
    post_text: str
    call_to_action_type: str
    suggested_cta_url: str

class GBPPostsResponse(BaseModel):
    post_1: GBPPost
    post_2: GBPPost

# --- 4. APP FASTAPI Y ENDPOINTS ---

app = FastAPI(title="SaaS GBP API Multitenant")

# A. Crear una Ficha independiente con su propia API Key y Prompt
@app.post("/api/v1/fichas")
def crear_ficha(ficha: FichaCreate, db: Session = Depends(get_db)):
    nueva_ficha = FichaGBP(
        nombre_negocio=ficha.nombre_negocio,
        categoria=ficha.categoria,
        ciudad=ficha.ciudad,
        gemini_api_key=ficha.gemini_api_key,
        prompt_custom=ficha.prompt_custom,
        gbp_auth_token=ficha.gbp_auth_token
    )
    db.add(nueva_ficha)
    db.commit()
    db.refresh(nueva_ficha)
    return {"status": "Ficha creada correctamente", "ficha_id": nueva_ficha.id}

# B. Listar todas las Fichas
@app.get("/api/v1/fichas")
def listar_fichas(db: Session = Depends(get_db)):
    return db.query(FichaGBP).all()

# C. Generar Posts USANDO LA API KEY Y PROMPT DE ESA FICHA
@app.post("/api/v1/fichas/{ficha_id}/generate-posts", response_model=GBPPostsResponse)
def generate_posts_para_ficha(ficha_id: int, request: ArticleRequest, db: Session = Depends(get_db)):
    # 1. Buscar la ficha en la base de datos
    ficha = db.query(FichaGBP).filter(FichaGBP.id == ficha_id).first()
    if not ficha:
        raise HTTPException(status_code=404, detail="Ficha GBP no encontrada")
    
    # 2. Construir el prompt (Usar el custom si existe, o uno genérico contextualizado)
    prompt_base = ficha.prompt_custom if ficha.prompt_custom else """
    Eres un experto en SEO Local y copywriting para Google Business Profile (GBP).
    Crea EXACTAMENTE 2 publicaciones para Google Business Profile enfocadas en la conversión local.
    """
    
    prompt_final = f"""
    {prompt_base}

    Contexto del Negocio:
    - Nombre del negocio: {ficha.nombre_negocio}
    - Categoría: {ficha.categoria}
    - Ubicación/Ciudad: {ficha.ciudad}

    Entradas para esta publicación:
    - Palabras Clave Objetivo: {request.target_keywords}
    - Contenido del Artículo Base:
    {request.article_content}
    """

    # 3. Inicializar el cliente de Gemini CON LA API KEY PROPIA DE ESTA FICHA
    try:
        client_custom = genai.Client(api_key=ficha.gemini_api_key)
        response = client_custom.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt_final,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GBPPostsResponse,
            ),
        )
        result_json = json.loads(response.text)
    except Exception as e:
        raise HTTPException(
            status_code=400, 
            detail=f"Error al generar con la API Key de la ficha '{ficha.nombre_negocio}': {str(e)}"
        )

    # 4. Guardar en el historial vinculado a la Ficha
    try:
        registro = PostRecord(
            ficha_id=ficha.id,
            keywords=request.target_keywords,
            post_1_text=result_json["post_1"]["post_text"],
            post_2_text=result_json["post_2"]["post_text"]
        )
        db.add(registro)
        db.commit()
    except Exception as db_err:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar historial: {str(db_err)}")

    return result_json
