from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from gimnasio.models import Clase, Plan, SesionClase, Socio

Usuario = get_user_model()


def crear_plan(nombre="Mensual", precio="25000", dias=30, activo=True):
    return Plan.objects.create(nombre=nombre, precio=Decimal(precio), duracion_dias=dias, activo=activo)


def crear_socio(nombre="Ana", documento=None, con_usuario=False):
    usuario = None
    if con_usuario:
        usuario = Usuario.objects.create_user(username=f"user_{nombre.lower()}_{Usuario.objects.count()}", password="clave-segura-123")
    return Socio.objects.create(
        nombre=nombre,
        apellido="Prueba",
        documento=documento or f"{nombre}-{Socio.objects.count() + 1}",
        user=usuario,
    )


def crear_clase(capacidad=2, nombre="Spinning"):
    return Clase.objects.create(nombre=nombre, instructor="Coach", capacidad=capacidad, duracion_minutos=45)


def crear_sesion(clase, horas_desde_ahora=24, capacidad=None):
    return SesionClase.objects.create(
        clase=clase,
        inicio=timezone.now() + timedelta(hours=horas_desde_ahora),
        capacidad=capacidad or clase.capacidad,
    )


def hoy():
    return timezone.localdate()
