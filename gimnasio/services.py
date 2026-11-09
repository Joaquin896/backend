"""Reglas de negocio de FitLife.

Toda operación que cambia varias filas usa transacciones y bloqueos de fila
(select_for_update) para que dos escaneos o dos reservas simultáneas no
rompan el aforo ni los cupos de una clase.
"""

import uuid
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import Membresia, Pago, RegistroAcceso, Reserva, SesionClase, Socio

# Clave fija para pg_advisory_xact_lock: serializa el cálculo de aforo al ingresar.
AFORO_LOCK_KEY = 4242_0001


class ReglaNegocioError(Exception):
    """Se lanza cuando una operación viola una regla del negocio (se traduce a HTTP 400/409)."""


def hoy():
    return timezone.localdate()


# ---------------------------------------------------------------------------
# Membresías
# ---------------------------------------------------------------------------

def membresia_vigente(socio, fecha=None):
    """Devuelve la membresía activa y no vencida del socio, o None."""
    fecha = fecha or hoy()
    return (
        Membresia.objects.filter(socio=socio, estado=Membresia.Estado.ACTIVA, fecha_fin__gte=fecha)
        .order_by("-fecha_fin")
        .first()
    )


def motivo_sin_membresia(socio):
    """Explica por qué el socio no tiene acceso, para mostrarlo en el torniquete."""
    ultima = Membresia.objects.filter(socio=socio).order_by("-fecha_fin").first()
    if ultima is None:
        return "Sin membresía registrada"
    estado = ultima.estado_efectivo()
    if estado == Membresia.Estado.CONGELADA:
        return "Membresía congelada"
    return "Membresía vencida"


def verificar_puede_contratar(socio, plan, fecha_inicio):
    """Lanza ReglaNegocioError si el plan no se puede vender a ese socio en esa fecha."""
    if not plan.activo:
        raise ReglaNegocioError("El plan seleccionado no está activo.")
    solapada = Membresia.objects.filter(
        socio=socio,
        estado__in=[Membresia.Estado.ACTIVA, Membresia.Estado.CONGELADA],
        fecha_fin__gte=fecha_inicio,
    ).exists()
    if solapada:
        raise ReglaNegocioError("El socio ya tiene una membresía vigente o congelada en esas fechas.")


@transaction.atomic
def registrar_membresia(socio, plan, fecha_inicio=None, metodo=Pago.Metodo.EFECTIVO, referencia="", usuario=None):
    """Crea la membresía y su pago inicial (por el precio del plan) en una sola transacción."""
    fecha_inicio = fecha_inicio or hoy()
    Socio.objects.select_for_update().get(pk=socio.pk)  # evita dos membresías simultáneas
    verificar_puede_contratar(socio, plan, fecha_inicio)

    membresia = Membresia.objects.create(
        socio=socio,
        plan=plan,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_inicio + timedelta(days=plan.duracion_dias - 1),
        estado=Membresia.Estado.ACTIVA,
    )
    Pago.objects.create(
        membresia=membresia,
        monto=plan.precio,
        metodo=metodo,
        referencia=referencia,
        registrado_por=usuario,
    )
    return membresia


@transaction.atomic
def congelar_membresia(membresia):
    membresia = Membresia.objects.select_for_update().get(pk=membresia.pk)
    if membresia.estado_efectivo() != Membresia.Estado.ACTIVA:
        raise ReglaNegocioError("Solo se puede congelar una membresía activa.")
    membresia.estado = Membresia.Estado.CONGELADA
    membresia.congelada_desde = hoy()
    membresia.save(update_fields=["estado", "congelada_desde"])
    return membresia


@transaction.atomic
def descongelar_membresia(membresia):
    """Reactiva la membresía y extiende su fecha de término por los días congelados."""
    membresia = Membresia.objects.select_for_update().get(pk=membresia.pk)
    if membresia.estado != Membresia.Estado.CONGELADA or membresia.congelada_desde is None:
        raise ReglaNegocioError("La membresía no está congelada.")
    dias = (hoy() - membresia.congelada_desde).days
    membresia.fecha_fin = membresia.fecha_fin + timedelta(days=dias)
    membresia.dias_congelados += dias
    membresia.estado = Membresia.Estado.ACTIVA
    membresia.congelada_desde = None
    membresia.save(update_fields=["fecha_fin", "dias_congelados", "estado", "congelada_desde"])
    return membresia


def actualizar_estados_membresias():
    """Marca como VENCIDA toda membresía ACTIVA cuya fecha de término ya pasó."""
    return Membresia.objects.filter(
        estado=Membresia.Estado.ACTIVA, fecha_fin__lt=hoy()
    ).update(estado=Membresia.Estado.VENCIDA)


# ---------------------------------------------------------------------------
# Control de acceso por QR
# ---------------------------------------------------------------------------

def _bloquear_aforo():
    """Bloqueo a nivel de base de datos mientras se calcula y ocupa un cupo de aforo."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [AFORO_LOCK_KEY])


def personas_dentro():
    return Socio.objects.filter(en_instalaciones=True).count()


def _registrar(socio, token, resultado, motivo, tipo="", usuario=None):
    return RegistroAcceso.objects.create(
        socio=socio,
        token_leido=token,
        resultado=resultado,
        tipo=tipo,
        motivo=motivo,
        registrado_por=usuario,
    )


@transaction.atomic
def registrar_acceso_qr(token, usuario=None):
    """Procesa la lectura de un QR.

    Reglas:
    - Si el socio ya está dentro, la lectura registra una SALIDA (siempre permitida).
    - Si no está dentro, se exige membresía ACTIVA y vigente para registrar ENTRADA.
    - No se permite superar FITLIFE_AFORO_MAXIMO.
    Siempre devuelve un RegistroAcceso (también para denegaciones) para auditoría.
    """
    token_texto = str(token or "").strip()[:100]

    try:
        qr = uuid.UUID(token_texto)
    except ValueError:
        return _registrar(None, token_texto, RegistroAcceso.Resultado.DENEGADO, "QR no válido", usuario=usuario)

    socio = Socio.objects.select_for_update().filter(qr_token=qr).first()
    if socio is None:
        return _registrar(None, token_texto, RegistroAcceso.Resultado.DENEGADO, "QR no reconocido", usuario=usuario)

    if socio.en_instalaciones:
        socio.en_instalaciones = False
        socio.save(update_fields=["en_instalaciones"])
        return _registrar(
            socio, token_texto, RegistroAcceso.Resultado.PERMITIDO,
            "Salida registrada", RegistroAcceso.Tipo.SALIDA, usuario,
        )

    if membresia_vigente(socio) is None:
        return _registrar(
            socio, token_texto, RegistroAcceso.Resultado.DENEGADO,
            motivo_sin_membresia(socio), usuario=usuario,
        )

    _bloquear_aforo()
    if personas_dentro() >= settings.FITLIFE_AFORO_MAXIMO:
        return _registrar(
            socio, token_texto, RegistroAcceso.Resultado.DENEGADO,
            "Aforo máximo alcanzado", usuario=usuario,
        )

    socio.en_instalaciones = True
    socio.save(update_fields=["en_instalaciones"])
    return _registrar(
        socio, token_texto, RegistroAcceso.Resultado.PERMITIDO,
        "Acceso concedido", RegistroAcceso.Tipo.ENTRADA, usuario,
    )


# ---------------------------------------------------------------------------
# Reservas, cupos y lista de espera
# ---------------------------------------------------------------------------

ESTADOS_ACTIVOS = [Reserva.Estado.CONFIRMADA, Reserva.Estado.ESPERA]


@transaction.atomic
def reservar_clase(socio, sesion):
    """Confirma la reserva si hay cupo; si la clase está llena, la anota en lista de espera."""
    sesion = SesionClase.objects.select_for_update().select_related("clase").get(pk=sesion.pk)

    if sesion.cancelada:
        raise ReglaNegocioError("La sesión fue cancelada.")
    if sesion.inicio <= timezone.now():
        raise ReglaNegocioError("La clase ya comenzó o terminó.")
    if membresia_vigente(socio) is None:
        raise ReglaNegocioError("Necesitas una membresía activa para reservar clases.")

    existente = Reserva.objects.select_for_update().filter(sesion=sesion, socio=socio).first()
    if existente and existente.estado in (*ESTADOS_ACTIVOS, Reserva.Estado.ASISTIO):
        raise ReglaNegocioError("Ya tienes una reserva para esta clase.")

    confirmadas = sesion.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count()
    if confirmadas < sesion.capacidad:
        estado, posicion = Reserva.Estado.CONFIRMADA, None
    else:
        ultima = sesion.reservas.filter(estado=Reserva.Estado.ESPERA).aggregate(m=Max("posicion_espera"))["m"]
        estado, posicion = Reserva.Estado.ESPERA, (ultima or 0) + 1

    if existente:  # reactivar una reserva cancelada previamente
        existente.estado = estado
        existente.posicion_espera = posicion
        existente.save(update_fields=["estado", "posicion_espera", "actualizada_en"])
        return existente

    return Reserva.objects.create(sesion=sesion, socio=socio, estado=estado, posicion_espera=posicion)


def _reordenar_lista_espera(sesion):
    en_espera = sesion.reservas.filter(estado=Reserva.Estado.ESPERA).order_by("posicion_espera", "creada_en")
    for posicion, reserva in enumerate(en_espera, start=1):
        if reserva.posicion_espera != posicion:
            Reserva.objects.filter(pk=reserva.pk).update(posicion_espera=posicion)


@transaction.atomic
def cancelar_reserva(reserva):
    """Cancela una reserva. Si liberó un cupo, el primero de la lista de espera pasa a confirmada."""
    sesion = SesionClase.objects.select_for_update().get(pk=reserva.sesion_id)
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)

    if reserva.estado not in ESTADOS_ACTIVOS:
        raise ReglaNegocioError("Solo se pueden cancelar reservas confirmadas o en lista de espera.")

    liberaba_cupo = reserva.estado == Reserva.Estado.CONFIRMADA
    reserva.estado = Reserva.Estado.CANCELADA
    reserva.posicion_espera = None
    reserva.save(update_fields=["estado", "posicion_espera", "actualizada_en"])

    if liberaba_cupo and not sesion.cancelada:
        siguiente = (
            sesion.reservas.filter(estado=Reserva.Estado.ESPERA)
            .order_by("posicion_espera", "creada_en")
            .first()
        )
        if siguiente:
            siguiente.estado = Reserva.Estado.CONFIRMADA
            siguiente.posicion_espera = None
            siguiente.save(update_fields=["estado", "posicion_espera", "actualizada_en"])

    _reordenar_lista_espera(sesion)
    return reserva


@transaction.atomic
def marcar_asistencia(reserva):
    reserva = Reserva.objects.select_for_update().get(pk=reserva.pk)
    if reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ReglaNegocioError("Solo se puede marcar asistencia a reservas confirmadas.")
    reserva.estado = Reserva.Estado.ASISTIO
    reserva.save(update_fields=["estado", "actualizada_en"])
    return reserva


# ---------------------------------------------------------------------------
# Dashboard de aforo
# ---------------------------------------------------------------------------

def resumen_dashboard(ahora=None):
    ahora = ahora or timezone.now()
    fecha = timezone.localtime(ahora).date()
    maximo = settings.FITLIFE_AFORO_MAXIMO
    dentro = personas_dentro()

    membresias = Membresia.objects
    inicio_dia = timezone.make_aware(datetime.combine(fecha, time.min))
    sesiones = (
        SesionClase.objects.filter(inicio__gte=inicio_dia, inicio__lt=inicio_dia + timedelta(days=1), cancelada=False)
        .select_related("clase")
        .annotate(
            confirmadas=Count("reservas", filter=Q(reservas__estado=Reserva.Estado.CONFIRMADA)),
            en_espera=Count("reservas", filter=Q(reservas__estado=Reserva.Estado.ESPERA)),
        )
        .order_by("inicio")
    )

    ultimos = (
        RegistroAcceso.objects.select_related("socio").order_by("-fecha_hora")[:10]
    )

    return {
        "actualizado_en": ahora.isoformat(),
        "aforo": {
            "personas_dentro": dentro,
            "maximo": maximo,
            "porcentaje": round(100 * dentro / maximo, 1) if maximo else 0,
        },
        "membresias": {
            "vigentes": membresias.vigentes().count(),
            "vencidas": membresias.vencidas().count(),
            "congeladas": membresias.congeladas().count(),
        },
        "clases_hoy": [
            {
                "id": s.id,
                "clase": s.clase.nombre,
                "instructor": s.clase.instructor,
                "inicio": timezone.localtime(s.inicio).strftime("%H:%M"),
                "capacidad": s.capacidad,
                "confirmadas": s.confirmadas,
                "en_espera": s.en_espera,
                "ocupacion": round(100 * s.confirmadas / s.capacidad, 1) if s.capacidad else 0,
            }
            for s in sesiones
        ],
        "ultimos_accesos": [
            {
                "socio": str(r.socio) if r.socio else r.token_leido,
                "resultado": r.get_resultado_display(),
                "tipo": r.get_tipo_display() if r.tipo else "",
                "motivo": r.motivo,
                "hora": timezone.localtime(r.fecha_hora).strftime("%H:%M:%S"),
            }
            for r in ultimos
        ],
    }
