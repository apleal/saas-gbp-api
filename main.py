import os
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai

app = FastAPI(title="SaaS GBP API")

# Configurar la API Key de Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Modelo de datos para la solicitud
class ArticleRequest(BaseModel):
    article_content: str
    target_keywords: str

# Modelo para la respuesta estructurada
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

@app.post("/api/v1/generate-gbp-posts", response_model=GBPPostsResponse)
def generate_gbp_posts(request: ArticleRequest):
    """
    Recibe el contenido de un blog y sus keywords para generar 2 posts optimizados para GBP.
    """
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
        # Configurar modelo Gemini 1.5 Flash indicando respuesta JSON estricta
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json", "response_schema": GBPPostsResponse}
        )
        
        response = model.generate_content(prompt)
        
        # Parsear el resultado JSON devuelto por Gemini
        result_json = json.loads(response.text)
        return result_json

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando con IA: {str(e)}")
        
