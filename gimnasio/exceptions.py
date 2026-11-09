from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.response import Response
from rest_framework import status

from .services import ReglaNegocioError


def manejador_excepciones(exc, context):
    """Convierte las violaciones de reglas de negocio en respuestas 400 con un mensaje claro."""
    if isinstance(exc, ReglaNegocioError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return drf_exception_handler(exc, context)
