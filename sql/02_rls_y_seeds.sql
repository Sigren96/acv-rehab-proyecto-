-- ============================================================
-- SISTEMA EMBEBIDO DE REHABILITACIÓN ACV - UNFV
-- Script 02: Row Level Security (RLS) + Datos semilla
-- ============================================================

-- ─────────────────────────────────────────
-- HABILITAR RLS EN TODAS LAS TABLAS
-- ─────────────────────────────────────────
ALTER TABLE public.especialistas    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pacientes        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.actividades      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sesiones         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resultados_rondas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dispositivos_pico ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────
-- POLÍTICAS: especialistas
-- Cada terapeuta solo ve y edita su propio perfil
-- ─────────────────────────────────────────
CREATE POLICY "especialista_select_own"
    ON public.especialistas FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "especialista_insert_own"
    ON public.especialistas FOR INSERT
    WITH CHECK (auth.uid() = id);

CREATE POLICY "especialista_update_own"
    ON public.especialistas FOR UPDATE
    USING (auth.uid() = id);

-- ─────────────────────────────────────────
-- POLÍTICAS: pacientes
-- El terapeuta solo gestiona sus propios pacientes
-- El paciente puede leer su propio perfil (por auth_user_id)
-- ─────────────────────────────────────────
CREATE POLICY "terapeuta_gestiona_pacientes"
    ON public.pacientes FOR ALL
    USING (especialista_id = auth.uid());

CREATE POLICY "paciente_lee_propio_perfil"
    ON public.pacientes FOR SELECT
    USING (auth_user_id = auth.uid());

-- ─────────────────────────────────────────
-- POLÍTICAS: actividades
-- ─────────────────────────────────────────
CREATE POLICY "terapeuta_gestiona_actividades"
    ON public.actividades FOR ALL
    USING (especialista_id = auth.uid());

-- ─────────────────────────────────────────
-- POLÍTICAS: sesiones
-- Terapeuta: acceso completo a sus sesiones
-- Paciente: solo lectura de sus propias sesiones
-- ─────────────────────────────────────────
CREATE POLICY "terapeuta_gestiona_sesiones"
    ON public.sesiones FOR ALL
    USING (especialista_id = auth.uid());

CREATE POLICY "paciente_lee_sesiones_propias"
    ON public.sesiones FOR SELECT
    USING (
        paciente_id IN (
            SELECT id FROM public.pacientes WHERE auth_user_id = auth.uid()
        )
    );

-- ─────────────────────────────────────────
-- POLÍTICAS: resultados_rondas
-- ─────────────────────────────────────────
CREATE POLICY "terapeuta_lee_resultados"
    ON public.resultados_rondas FOR SELECT
    USING (
        sesion_id IN (
            SELECT id FROM public.sesiones WHERE especialista_id = auth.uid()
        )
    );

CREATE POLICY "backend_inserta_resultados"
    ON public.resultados_rondas FOR INSERT
    WITH CHECK (TRUE);   -- El backend usa service_role key, sin restricción

-- ─────────────────────────────────────────
-- POLÍTICAS: dispositivos_pico
-- ─────────────────────────────────────────
CREATE POLICY "terapeuta_lee_dispositivo"
    ON public.dispositivos_pico FOR SELECT
    USING (
        sesion_id IN (
            SELECT id FROM public.sesiones WHERE especialista_id = auth.uid()
        )
    );

-- ─────────────────────────────────────────
-- FUNCIÓN: registrar_especialista
-- Se llama desde el backend al hacer signup con rol=terapeuta
-- ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.registrar_especialista(
    p_id        UUID,
    p_nombres   TEXT,
    p_apellidos TEXT,
    p_email     TEXT,
    p_especialidad TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO public.especialistas(id, nombres, apellidos, email, especialidad)
    VALUES (p_id, p_nombres, p_apellidos, p_email, p_especialidad)
    ON CONFLICT (id) DO NOTHING;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ─────────────────────────────────────────
-- FUNCIÓN: generar_pin_unico
-- Genera un PIN de 6 dígitos no repetido en la tabla pacientes
-- ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.generar_pin_unico()
RETURNS CHAR(6) AS $$
DECLARE
    v_pin CHAR(6);
    v_existe BOOLEAN;
BEGIN
    LOOP
        v_pin := LPAD(FLOOR(RANDOM() * 1000000)::TEXT, 6, '0');
        SELECT EXISTS(SELECT 1 FROM public.pacientes WHERE pin_acceso = v_pin)
        INTO v_existe;
        EXIT WHEN NOT v_existe;
    END LOOP;
    RETURN v_pin;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────
-- DATOS SEMILLA: actividades predefinidas
-- (se insertan con un especialista_id ficticio nulo;
--  en producción usar un UUID de sistema o ajustar RLS)
-- ─────────────────────────────────────────
-- Nota: estas actividades predefinidas son visibles para todos.
-- Ajusta la política si quieres que sean globales.

-- ─────────────────────────────────────────
-- VISTA: resumen_sesiones (útil para el historial)
-- ─────────────────────────────────────────
CREATE OR REPLACE VIEW public.vista_resumen_sesiones AS
SELECT
    s.id                                            AS sesion_id,
    s.paciente_id,
    p.nombres || ' ' || p.apellidos                 AS paciente_nombre,
    s.especialista_id,
    e.nombres || ' ' || e.apellidos                 AS especialista_nombre,
    s.estado,
    s.nivel_dificultad,
    s.num_rondas,
    s.porcentaje_go,
    s.iniciada_at,
    s.finalizada_at,
    EXTRACT(EPOCH FROM (s.finalizada_at - s.iniciada_at))::INTEGER AS duracion_seg,
    COUNT(r.id)                                     AS rondas_ejecutadas,
    COUNT(r.id) FILTER (WHERE r.resultado = 'acierto') AS aciertos,
    COUNT(r.id) FILTER (WHERE r.resultado = 'error')   AS errores,
    COUNT(r.id) FILTER (WHERE r.resultado = 'timeout') AS timeouts,
    ROUND(AVG(r.latencia_ms))                       AS latencia_promedio_ms,
    ROUND(AVG(r.angulo_final_deg)::NUMERIC, 2)      AS angulo_promedio_deg,
    ROUND(AVG(r.tasa_temblor)::NUMERIC, 6)          AS temblor_promedio
FROM public.sesiones s
JOIN public.pacientes    p ON p.id = s.paciente_id
JOIN public.especialistas e ON e.id = s.especialista_id
LEFT JOIN public.resultados_rondas r ON r.sesion_id = s.id
GROUP BY s.id, p.nombres, p.apellidos, e.nombres, e.apellidos;
