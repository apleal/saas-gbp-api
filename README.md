
# SaaS GBP API

API multitenant para gestionar fichas de Google Business Profile y generar
publicaciones con la clave de Gemini de cada ficha.

## Variables de entorno

- `DATABASE_URL`: URL de PostgreSQL. En desarrollo usa SQLite si no se define.
- `JWT_SECRET_KEY`: secreto obligatorio para firmar los tokens.
- `ACCESS_TOKEN_EXPIRE_MINUTES`: duración del token; por defecto, 1440 minutos.
- `GOOGLE_CLIENT_ID`: cliente OAuth web del proyecto de Google Cloud.
- `GOOGLE_CLIENT_SECRET`: secreto del cliente OAuth.
- `GOOGLE_REDIRECT_URI`: callback OAuth público y autorizado en Google Cloud.
- `TOKEN_ENCRYPTION_KEY`: clave Fernet para cifrar los refresh tokens.

Genera un secreto seguro, por ejemplo:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Ejecución

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

El panel se sirve en `/` y la documentación OpenAPI en `/docs`.

## Importación desde Google Business Profile

El usuario conecta la cuenta Google que administra sus negocios. La aplicación
consulta sus cuentas y ubicaciones, permite seleccionar hasta cinco e importa
los datos del perfil y sus reseñas. Los tokens de acceso se renuevan en el
servidor y el refresh token nunca se expone al navegador.

## Despliegue de la versión multitenant

Al iniciar, la aplicación crea la tabla de usuarios y añade `owner_id` si
detecta la tabla antigua `fichas_gbp`. Las fichas anteriores quedan sin
propietario y no se muestran a ningún usuario. Deben asignarse manualmente a
la cuenta correspondiente antes de eliminar esa compatibilidad.
