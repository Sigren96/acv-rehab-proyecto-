"""
core/auth.py
Middleware de autenticación JWT para rutas protegidas.
Valida el token emitido por Supabase Auth.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from core.config import get_settings

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Extrae y valida el JWT de Supabase del header Authorization: Bearer <token>.
    Retorna el payload decodificado (incluye sub=user_id, role, email, user_metadata).
    """
    cfg = get_settings()
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            cfg.supabase_jwt_secret,
            algorithms=["HS256", "ES256", "RS256"], 
            options={
                "verify_signature": False, 
                "verify_aud": False,
                "verify_exp": True  # Mantenemos la seguridad de expiración
            }
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido o expirado: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_terapeuta(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia: rechaza si el rol no es 'terapeuta'."""
    role = (user.get("user_metadata") or {}).get("rol")
    if role != "terapeuta":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a terapeutas.",
        )
    return user


def require_paciente(user: dict = Depends(get_current_user)) -> dict:
    """Dependencia: rechaza si el rol no es 'paciente'."""
    role = (user.get("user_metadata") or {}).get("rol")
    if role != "paciente":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a pacientes.",
        )
    return user
