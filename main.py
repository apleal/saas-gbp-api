import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI(title="SaaS GBP API")

# Inicializar cliente oficial de Gemini
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
    return {"mensaje": "API de Python lista y funcionando en Easypanel"}

@app.get("/api/v1/models")
def list_available_models():
    """
    Lista todos los modelos a los que tu API Key tiene acceso.
    """
    try:
        models = [m.name for m in client.models.list()]
        return {"modelos_disponibles": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate-gbp-posts", response_model=GBPPostsResponse)
def generate_gbp_posts(request: ArticleRequest):
    prompt = f"""
    Eres un experto en SEO Local y copywriting para Google Business Profile (GBP).
    A partir del siguiente artículo de blog y palabras clave, crea EXACTAMENTE 2 publicaciones para Google Business Profile.

    Directrices:
    - Post 1: Enfoque informativo/educativo. Destaca un problema o dato clave del artículo.
    - Post 2: Enfoque directo a la conversión/oferta. Invita a la acción clara para contactar o contratar.
    - Mantén los textos concisos, con gancho inicial, emojis relevantes y optimizados para búsquedas locales usando las keywords indicadas.
    - Texto humanizado

    Palabras Clave Objetivo: {request.target_keywords}
    Contenido del Artículo:
    {request.article_content}
    """

    try:
        # Usamos el alias oficial que siempre apunta al último Flash estable de tu lista
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GBPPostsResponse,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando con IA: {str(e)}")
        
