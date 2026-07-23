import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

# --- 1. CONEXIÓN A POSTGRESQL ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Corrección de seguridad para el prefijo de SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. MODELO DE LA TABLA ---
class PostRecord(Base):
    __tablename__ = "historial_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    keywords = Column(String(255))
    post_1_text = Column(Text)
    post_2_text = Column(Text)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- 3. APP FASTAPI ---
app = FastAPI(title="SaaS GBP API")
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

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

@app.get("/")
def home():
    return {"status": "ok", "db_connected": bool(DATABASE_URL)}

@app.post("/api/v1/generate-gbp-posts", response_model=GBPPostsResponse)
def generate_gbp_posts(request: ArticleRequest):
    prompt = f"""
    Eres un experto en SEO Local y copywriting para Google Business Profile (GBP).
    A partir del siguiente artículo de blog y palabras clave, crea EXACTAMENTE 2 publicaciones para Google Business Profile.

    Directrices:
    - Post 1: Enfoque informativo/educativo.
    - Post 2: Enfoque directo a la conversión/oferta.

    Palabras Clave Objetivo: {request.target_keywords}
    Contenido del Artículo:
    {request.article_content}
    """

    # 1. Generar con Gemini
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GBPPostsResponse,
            ),
        )
        result_json = json.loads(response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar con Gemini: {str(e)}")

    # 2. Guardado explícito en PostgreSQL
    db = SessionLocal()
    try:
        registro = PostRecord(
            keywords=request.target_keywords,
            post_1_text=result_json["post_1"]["post_text"],
            post_2_text=result_json["post_2"]["post_text"]
        )
        db.add(registro)
        db.commit()      # Confirmación obligatoria
        db.refresh(registro)
    except Exception as db_err:
        db.rollback()    # Si falla, deshace cambios
        raise HTTPException(status_code=500, detail=f"Error guardando en la Base de Datos: {str(db_err)}")
    finally:
        db.close()       # Cierra la conexión siempre

    return result_json
