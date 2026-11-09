from rest_framework.permissions import SAFE_METHODS, BasePermission


class EsStaff(BasePermission):
    """Administradores y recepción: acceso completo a la gestión del centro."""

    message = "Se requiere una cuenta de personal (staff)."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class StaffEscribeOLecturaAutenticada(BasePermission):
    """Cualquier usuario autenticado puede leer; solo el staff puede crear/editar/borrar."""

    message = "Solo el personal puede modificar este recurso."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or request.user.is_staff


class EsDuenoOStaff(BasePermission):
    """Permite a un socio ver/usar solo sus propios datos; el staff ve todo."""

    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        socio = getattr(obj, "socio", obj)
        return socio.user_id == request.user.id
