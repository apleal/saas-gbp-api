import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from google import genai
from google.genai import types
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# --- 1. CONFIGURACIÓN DE LA BASE DE DATOS ---
DATABASE_URL = os.environ.get("DATABASE_URL")
# SQLAlchemy necesita que la URL empiece por postgresql://
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. CREACIÓN DE LA TABLA ---
class PostRecord(Base):
    __tablename__ = "historial_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    keywords = Column(String, index=True)
    post_1_text = Column(Text)
    post_2_text = Column(Text)
    fecha_creacion = Column(DateTime, default=datetime.utcnow)

# Esto crea la tabla automáticamente si no existe al arrancar la API
Base.metadata.create_all(bind=engine)

# Función para abrir y cerrar la conexión con la BD en cada petición
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 3. CONFIGURACIÓN DE LA API Y GEMINI ---
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
    return {"mensaje": "API conectada a PostgreSQL y funcionando correctamente"}

@app.post("/api/v1/generate-gbp-posts", response_model=GBPPostsResponse)
def generate_gbp_posts(request: ArticleRequest, db: Session = Depends(get_db)):
    prompt = f"""
    Eres un experto en SEO Local y copywriting para Google Business Profile (GBP).
    A partir del siguiente artículo de blog y palabras clave, crea EXACTAMENTE 2 publicaciones para Google Business Profile.

    Directrices:
    - Post 1: Enfoque informativo/educativo. Destaca un problema o dato clave del artículo.
    - Post 2: Enfoque directo a la conversión/oferta. Invita a la acción clara para contactar o contratar.
    - Mantén los textos concisos, con gancho inicial, emojis relevantes y optimizados para búsquedas locales usando las keywords indicadas.

    Palabras Clave Objetivo: {request.target_keywords}
    Contenido del Artículo:
    {request.article_content}
    """

    try:
        # Generar contenido con Gemini
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GBPPostsResponse,
            ),
        )
        result_json = json.loads(response.text)

        # --- 4. GUARDAR EN LA BASE DE DATOS ---
        nuevo_registro = PostRecord(
            keywords=request.target_keywords,
            post_1_text=result_json["post_1"]["post_text"],
            post_2_text=result_json["post_2"]["post_text"]
        )
        db.add(nuevo_registro)
        db.commit() # Confirmamos el guardado

        # Devolvemos el JSON al usuario
        return result_json

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando con IA o Base de Datos: {str(e)}")
