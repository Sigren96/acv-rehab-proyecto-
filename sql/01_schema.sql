-- ============================================================
-- SISTEMA EMBEBIDO DE REHABILITACIÓN ACV - UNFV
-- Script 01: Schema principal de base de datos
-- Plataforma: Supabase (PostgreSQL)
-- ============================================================

-- ─────────────────────────────────────────
-- EXTENSIONES
-- ─────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────
-- TABLA: especialistas
-- Vinculada a auth.users de Supabase Auth
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.especialistas (
    id             UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    nombres        TEXT NOT NULL,
    apellidos      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    especialidad   TEXT,
    telefono       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- TABLA: pacientes
-- El terapeuta los crea; acceden con PIN
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.pacientes (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    especialista_id   UUID NOT NULL REFERENCES public.especialistas(id) ON DELETE CASCADE,
    auth_user_id      UUID UNIQUE REFERENCES auth.users(id) ON DELETE SET NULL,
    nombres           TEXT NOT NULL,
    apellidos         TEXT NOT NULL,
    fecha_nacimiento  DATE,
    diagnostico       TEXT,
    nivel_movilidad   TEXT NOT NULL DEFAULT 'critico'
                      CHECK (nivel_movilidad IN ('critico', 'intermedio', 'recuperado')),
    pin_acceso        CHAR(6) NOT NULL UNIQUE,
    activo            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- TABLA: actividades
-- Biblioteca de ejercicios del terapeuta
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.actividades (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    especialista_id     UUID NOT NULL REFERENCES public.especialistas(id) ON DELETE CASCADE,
    nombre              TEXT NOT NULL,
    descripcion_clinica TEXT,
    eje_movimiento      TEXT NOT NULL CHECK (eje_movimiento IN ('X', 'Y', 'Z')),
    patron_validacion   TEXT NOT NULL CHECK (patron_validacion IN ('lineal', 'rotacion')),
    es_predefinida      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- TABLA: sesiones
-- Una sesión de terapia por paciente
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sesiones (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    paciente_id         UUID NOT NULL REFERENCES public.pacientes(id) ON DELETE CASCADE,
    especialista_id     UUID NOT NULL REFERENCES public.especialistas(id) ON DELETE CASCADE,
    actividad_id        UUID REFERENCES public.actividades(id) ON DELETE SET NULL,
    estado              TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente', 'en_curso', 'completada', 'abortada')),
    nivel_dificultad    TEXT NOT NULL DEFAULT 'facil'
                        CHECK (nivel_dificultad IN ('facil', 'medio', 'dificil')),
    num_rondas          INTEGER NOT NULL DEFAULT 10 CHECK (num_rondas BETWEEN 1 AND 50),
    tiempo_descanso_seg INTEGER NOT NULL DEFAULT 3  CHECK (tiempo_descanso_seg BETWEEN 1 AND 30),
    porcentaje_go       INTEGER NOT NULL DEFAULT 70 CHECK (porcentaje_go BETWEEN 10 AND 90),
    -- tmax calculado según dificultad: facil=3.5s, medio=1.8s, dificil=0.8s
    tmax_seg            NUMERIC(4,2) NOT NULL DEFAULT 3.50,
    umbral_g            NUMERIC(5,3) NOT NULL DEFAULT 0.730,
    iniciada_at         TIMESTAMPTZ,
    finalizada_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- TABLA: resultados_rondas
-- Métricas calculadas por ronda (no datos crudos)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.resultados_rondas (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sesion_id           UUID NOT NULL REFERENCES public.sesiones(id) ON DELETE CASCADE,
    numero_ronda        INTEGER NOT NULL,
    tipo_estimulo       TEXT NOT NULL CHECK (tipo_estimulo IN ('GO', 'NO-GO')),
    direccion_objetivo  TEXT CHECK (direccion_objetivo IN ('arriba', 'abajo', 'izquierda', 'derecha', 'circulo', NULL)),
    resultado           TEXT NOT NULL CHECK (resultado IN ('acierto', 'error', 'timeout')),
    -- Métricas calculadas en backend
    latencia_ms         INTEGER,          -- ms desde t0 hasta primer movimiento detectado
    angulo_final_deg    NUMERIC(7,3),     -- grados acumulados por integración del giroscopio
    tasa_temblor        NUMERIC(10,6),    -- varianza de magnitud vectorial (sin gravedad)
    -- Timestamp de la ronda
    ejecutada_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- TABLA: dispositivos_pico
-- Registro de la Raspberry Pi Pico por sesión
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dispositivos_pico (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sesion_id       UUID UNIQUE REFERENCES public.sesiones(id) ON DELETE CASCADE,
    ip_origen       TEXT,
    ultimo_ping     TIMESTAMPTZ,
    paquetes_recibidos INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────
-- ÍNDICES para consultas frecuentes
-- ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_pacientes_especialista   ON public.pacientes(especialista_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_paciente        ON public.sesiones(paciente_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_especialista    ON public.sesiones(especialista_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_estado          ON public.sesiones(estado);
CREATE INDEX IF NOT EXISTS idx_resultados_sesion        ON public.resultados_rondas(sesion_id);
CREATE INDEX IF NOT EXISTS idx_pacientes_pin            ON public.pacientes(pin_acceso);

-- ─────────────────────────────────────────
-- TRIGGER: actualizar updated_at automáticamente
-- ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_especialistas_updated
    BEFORE UPDATE ON public.especialistas
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_pacientes_updated
    BEFORE UPDATE ON public.pacientes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
