# SaaS GBP API

Base del backend para un SaaS que permitirá a agencias, consultores SEO y pymes
conectar hasta tres fichas existentes de Google Business Profile, preparar contenido
y automatizar publicaciones.

## Primera fase

Esta fase incluye:

- Aplicación FastAPI modular.
- Usuarios, organizaciones y membresías.
- Registro, autenticación con token Bearer y consulta del usuario actual.
- Organización inicial con plan `starter` y límite configurable de tres fichas.
- Configuración mediante variables de entorno.
- Migraciones de base de datos con Alembic.
- Pruebas de integración con SQLite en memoria.

La conexión e importación de fichas existentes desde Google se implementará en la
siguiente fase. No se solicitan nuevamente al usuario los datos públicos de la ficha.

## Configuración local

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Exporta las variables de `.env` con tu método preferido. Para PostgreSQL, crea la
base indicada por `DATABASE_URL` y ejecuta:

```bash
alembic upgrade head
uvicorn main:app --reload
```

La documentación interactiva estará disponible en `http://127.0.0.1:8000/docs`.

En desarrollo, si no se proporciona `DATABASE_URL`, se usa `sqlite:///./saas_gbp.db`.
Este valor facilita una prueba rápida, pero PostgreSQL es la base prevista para el
despliegue.

## Variables de entorno

| Variable | Descripción | Valor de desarrollo |
| --- | --- | --- |
| `APP_NAME` | Nombre mostrado por FastAPI | `SaaS GBP API` |
| `ENVIRONMENT` | Entorno de ejecución | `development` |
| `DATABASE_URL` | URL de conexión SQLAlchemy | SQLite local |
| `JWT_SECRET_KEY` | Secreto usado para firmar tokens | Solo valor inseguro de desarrollo |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del token | `30` |
| `MAX_PROFILES_PER_ORGANIZATION` | Límite inicial del plan | `3` |

En producción, la aplicación rechaza el secreto predeterminado de desarrollo.

## API inicial

### Registro

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "cliente@example.com",
    "password": "una-clave-muy-segura",
    "full_name": "Cliente Ejemplo",
    "organization_name": "Agencia Local"
  }'
```

### Inicio de sesión

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"cliente@example.com","password":"una-clave-muy-segura"}'
```

### Usuario actual

```bash
curl http://127.0.0.1:8000/api/v1/auth/me \
  -H 'Authorization: Bearer TOKEN'
```

## Pruebas

```bash
pytest -q
```

Las pruebas no requieren PostgreSQL ni realizan llamadas externas.
