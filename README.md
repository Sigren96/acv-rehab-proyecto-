# Sistema Embebido de Rehabilitación Cognitivo-Motora ACV
### Universidad Nacional Federico Villarreal — 2026

---

## Arquitectura General

```
Raspberry Pi Pico W
  │  HTTP POST /api/v1/telemetria  (cada 500 ms, 10 muestras IMU)
  ▼
Backend FastAPI (Railway / Fly.io)
  │  WebSocket ws://backend/ws/terapeuta/{sesion_id}
  │  WebSocket ws://backend/ws/paciente/{paciente_id}
  ▼                        ▼
Dashboard Terapeuta    Vista Paciente
(Vercel — HTML/CSS/JS) (Vercel — HTML/CSS/JS)
  │
  └── Supabase (PostgreSQL + Auth)
```

---

## Estructura de Archivos

```
acv-rehab/
├── sql/
│   ├── 01_schema.sql          ← Tablas, índices, triggers, vista resumen
│   └── 02_rls_y_seeds.sql     ← RLS policies, funciones helper
│
├── backend/
│   ├── main.py                ← FastAPI app + CORS + lifespan
│   ├── requirements.txt
│   ├── .env.example           ← Copia a .env y rellena
│   ├── core/
│   │   ├── config.py          ← Settings (Pydantic) desde .env
│   │   ├── database.py        ← Clientes Supabase (service + anon)
│   │   └── auth.py            ← Validación JWT + dependencias de rol
│   ├── models/
│   │   └── schemas.py         ← Pydantic schemas (request/response)
│   ├── services/
│   │   ├── fsm_sesion.py      ← FSM + ProcesadorIMU (métricas)
│   │   └── connection_manager.py ← WebSocket manager + loop de rondas
│   └── routers/
│       └── api.py             ← Todos los endpoints HTTP + WebSocket
│
└── frontend/
    ├── vercel.json
    ├── pages/
    │   ├── index.html         ← Login + selector de rol
    │   ├── dashboard.html     ← Dashboard completo del terapeuta
    │   └── paciente.html      ← Vista de estímulos GO/NO-GO
    ├── css/
    │   └── styles.css         ← Design system completo (Mobile-First)
    └── js/
        ├── api.js             ← Cliente HTTP + WsManager + Auth
        ├── audio.js           ← Web Audio API (todos los tonos)
        ├── app.js             ← Controlador del dashboard terapeuta
        └── paciente.js        ← Controlador de la vista paciente
```

---

## Paso 1 — Supabase

1. Crea un proyecto en [supabase.com](https://supabase.com)
2. Ve a **SQL Editor** y ejecuta en orden:
   ```
   01_schema.sql
   02_rls_y_seeds.sql
   ```
3. Copia desde **Settings > API**:
   - `Project URL`
   - `anon public` key
   - `service_role` key
   - `JWT Secret` (Settings > API > JWT Settings)

---

## Paso 2 — Backend (Windows + venv)

```bash
# Desde la carpeta backend/
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

# Copia .env.example a .env y rellena los valores
copy .env.example .env

# Desarrollo local
uvicorn main:app --reload --port 8000
```

Verifica en: `http://localhost:8000/docs` (Swagger UI automático de FastAPI)

### Variables de entorno requeridas (.env)

| Variable | Descripción |
|---|---|
| `SUPABASE_URL` | URL de tu proyecto Supabase |
| `SUPABASE_ANON_KEY` | Clave pública anon |
| `SUPABASE_SERVICE_KEY` | Clave service_role (SOLO backend) |
| `SUPABASE_JWT_SECRET` | Secret para validar tokens JWT |
| `FRONTEND_URL` | URL de Vercel (para CORS) |

### Deploy en Railway

```bash
# En Railway: conectar repo GitHub → seleccionar carpeta backend/
# Configurar variables de entorno desde el dashboard de Railway
# Railway detecta automáticamente FastAPI y corre uvicorn
```

---

## Paso 3 — Frontend (Vercel)

1. Sube la carpeta `frontend/` a un repositorio GitHub
2. En [vercel.com](https://vercel.com): **New Project → Import Git**
3. En **Environment Variables** agrega:
   ```
   ENV_API_BASE = https://tu-backend.railway.app/api/v1
   ```
4. Vercel detecta `vercel.json` y despliega automáticamente

---

## Paso 4 — Firmware Raspberry Pi Pico W

El JSON que debe enviar la Pico cada 500 ms:

```json
{
  "sesion_id": "UUID-de-la-sesion-activa",
  "muestras": [
    {"x": 0.012, "y": -0.456, "z": 0.981, "gx": 1.2, "gy": -0.5, "gz": 0.1},
    ...
    (exactamente 10 objetos)
  ]
}
```

Endpoint destino:
```
POST https://tu-backend.railway.app/api/v1/telemetria
Content-Type: application/json
```

El `sesion_id` se obtiene desde el dashboard del terapeuta al crear la sesión (vista "Nueva Sesión").

---

## Flujo de Uso Completo

```
1. Terapeuta → index.html → Login con email/contraseña
2. Terapeuta → dashboard → Registra paciente → obtiene PIN (ej: 482917)
3. Terapeuta → Nueva Sesión → configura rondas, dificultad, GO/NO-GO %
4. Terapeuta → obtiene sesion_id → lo ingresa en el firmware de la Pico
5. Paciente  → index.html → Ingresa PIN → entra a vista de espera
6. Terapeuta → hace clic "Crear y pasar a monitoreo"
7. Backend   → inicia FSM, notifica al paciente por WebSocket
8. Paciente  → ve flechas/cruces GO/NO-GO en pantalla
9. Pico      → envía IMU cada 500 ms → backend procesa → retransmite al terapeuta
10. Backend  → calcula métricas, guarda en Supabase, notifica resultados
11. Al final → terapeuta descarga PDF, paciente ve resumen
```

---

## Métricas Calculadas (por ronda)

| Métrica | Fórmula | Unidad |
|---|---|---|
| Latencia Motriz | `t_movimiento - t0_estimulo` | ms |
| Precisión Rotación | `Σ(velocidad_angular × 0.05s)` | grados |
| Tasa de Temblor | `Var(√(x²+y²+(z-1)²))` | adimensional |

---

## Notas de Seguridad

- La `SUPABASE_SERVICE_KEY` **nunca** debe aparecer en el frontend
- Las políticas RLS garantizan que cada terapeuta solo accede a sus propios pacientes
- Los tokens JWT de Supabase expiran automáticamente (configurar refresh en producción)
- En producción, configurar HTTPS tanto en Railway como en Vercel

---

*Proyecto académico — Sistemas Digitales y Arquitectura de Computadoras — UNFV 2026*
