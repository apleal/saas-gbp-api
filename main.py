import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

app = FastAPI(title="SaaS GBP API")

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

@app.post("/api/v1/generate-gbp-posts", response_model=GBPPostsResponse)
async def generate_gbp_posts(request: ArticleRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Falta la variable GEMINI_API_KEY en Easypanel")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

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

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "post_1": {
                        "type": "OBJECT",
                        "properties": {
                            "post_type": {"type": "STRING"},
                            "post_text": {"type": "STRING"},
                            "call_to_action_type": {"type": "STRING"},
                            "suggested_cta_url": {"type": "STRING"}
                        },
                        "required": ["post_type", "post_text", "call_to_action_type", "suggested_cta_url"]
                    },
                    "post_2": {
                        "type": "OBJECT",
                        "properties": {
                            "post_type": {"type": "STRING"},
                            "post_text": {"type": "STRING"},
                            "call_to_action_type": {"type": "STRING"},
                            "suggested_cta_url": {"type": "STRING"}
                        },
                        "required": ["post_type", "post_text", "call_to_action_type", "suggested_cta_url"]
                    }
                },
                "required": ["post_1", "post_2"]
            }
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=30.0)
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Error en Google API: {response.text}")
        
        data = response.json()
        try:
            # Extraer la respuesta JSON devuelta por Gemini
            text_response = data["candidates"][0]["content"]["parts"][0]["text"]
            import json
            return json.loads(text_response)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al parsear respuesta: {str(e)}")
        
