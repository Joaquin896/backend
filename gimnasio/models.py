"""Modelo de dominio de FitLife: planes, socios, membresías, pagos, clases, reservas y accesos."""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Plan(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    duracion_dias = models.PositiveIntegerField(
        validators=[MinValueValidator(1)], help_text="Días de vigencia de la membresía."
    )
    activo = models.BooleanField(default=True, help_text="Los planes inactivos no se pueden vender.")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "plan"
        verbose_name_plural = "planes"

    def __str__(self):
        return f"{self.nombre} ({self.duracion_dias} días)"


class Socio(models.Model):
    """Persona inscrita en el centro. Puede tener un usuario para ingresar a la web/API."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="socio",
        help_text="Usuario para iniciar sesión (opcional).",
    )
    documento = models.CharField("RUT / documento", max_length=20, unique=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    en_instalaciones = models.BooleanField(
        default=False, help_text="Se actualiza automáticamente con cada escaneo de QR."
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["apellido", "nombre"]
        verbose_name = "socio"
        verbose_name_plural = "socios"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class MembresiaQuerySet(models.QuerySet):
    def vigentes(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.filter(estado=Membresia.Estado.ACTIVA, fecha_fin__gte=hoy)

    def vencidas(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.filter(
            Q(estado=Membresia.Estado.VENCIDA)
            | Q(estado=Membresia.Estado.ACTIVA, fecha_fin__lt=hoy)
        )

    def congeladas(self):
        return self.filter(estado=Membresia.Estado.CONGELADA)


class Membresia(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        VENCIDA = "VENCIDA", "Vencida"
        CONGELADA = "CONGELADA", "Congelada"

    socio = models.ForeignKey(Socio, on_delete=models.PROTECT, related_name="membresias")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="membresias")
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(help_text="Último día con acceso (inclusive).")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA)
    congelada_desde = models.DateField(null=True, blank=True)
    dias_congelados = models.PositiveIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)

    objects = MembresiaQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha_inicio"]
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        constraints = [
            models.CheckConstraint(
                condition=Q(fecha_fin__gte=models.F("fecha_inicio")),
                name="membresia_fin_no_anterior_a_inicio",
            ),
        ]

    def __str__(self):
        return f"{self.socio} - {self.plan} ({self.get_estado_display()})"

    def estado_efectivo(self, hoy=None):
        """Estado real a la fecha, aunque el campo almacenado todavía diga ACTIVA."""
        hoy = hoy or timezone.localdate()
        if self.estado == self.Estado.CONGELADA:
            return self.Estado.CONGELADA
        if self.estado == self.Estado.VENCIDA or self.fecha_fin < hoy:
            return self.Estado.VENCIDA
        return self.Estado.ACTIVA


class Pago(models.Model):
    class Metodo(models.TextChoices):
        EFECTIVO = "EFECTIVO", "Efectivo"
        TARJETA = "TARJETA", "Tarjeta"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"

    membresia = models.ForeignKey(Membresia, on_delete=models.PROTECT, related_name="pagos")
    monto = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    metodo = models.CharField(max_length=15, choices=Metodo.choices, default=Metodo.EFECTIVO)
    referencia = models.CharField(max_length=60, blank=True)
    fecha_pago = models.DateTimeField(default=timezone.now)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pagos_registrados",
    )

    class Meta:
        ordering = ["-fecha_pago"]
        verbose_name = "pago"
        verbose_name_plural = "pagos"

    def __str__(self):
        return f"Pago ${self.monto} de {self.membresia.socio}"


class Clase(models.Model):
    """Definición de una clase grupal (p. ej. Spinning, Yoga)."""

    nombre = models.CharField(max_length=100, unique=True)
    instructor = models.CharField(max_length=100, blank=True)
    descripcion = models.TextField(blank=True)
    duracion_minutos = models.PositiveIntegerField(validators=[MinValueValidator(5)], default=60)
    capacidad = models.PositiveIntegerField(
        validators=[MinValueValidator(1)], help_text="Cupos por defecto de cada sesión."
    )
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "clase grupal"
        verbose_name_plural = "clases grupales"

    def __str__(self):
        return self.nombre


class SesionClase(models.Model):
    """Una clase programada en fecha y hora concreta, con cupo propio."""

    clase = models.ForeignKey(Clase, on_delete=models.PROTECT, related_name="sesiones")
    inicio = models.DateTimeField()
    capacidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    cancelada = models.BooleanField(default=False)

    class Meta:
        ordering = ["inicio"]
        verbose_name = "sesión de clase"
        verbose_name_plural = "sesiones de clase"
        constraints = [
            models.UniqueConstraint(fields=["clase", "inicio"], name="sesion_unica_por_horario"),
        ]

    def __str__(self):
        return f"{self.clase} - {timezone.localtime(self.inicio):%d/%m %H:%M}"

    @property
    def fin(self):
        return self.inicio + timedelta(minutes=self.clase.duracion_minutos)

    def save(self, *args, **kwargs):
        if not self.capacidad and self.clase_id:
            self.capacidad = self.clase.capacidad
        super().save(*args, **kwargs)


class Reserva(models.Model):
    class Estado(models.TextChoices):
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        ESPERA = "ESPERA", "En lista de espera"
        CANCELADA = "CANCELADA", "Cancelada"
        ASISTIO = "ASISTIO", "Asistió"

    sesion = models.ForeignKey(SesionClase, on_delete=models.PROTECT, related_name="reservas")
    socio = models.ForeignKey(Socio, on_delete=models.PROTECT, related_name="reservas")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.CONFIRMADA)
    posicion_espera = models.PositiveIntegerField(null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sesion__inicio", "posicion_espera", "creada_en"]
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        constraints = [
            models.UniqueConstraint(fields=["sesion", "socio"], name="reserva_unica_por_socio_sesion"),
        ]

    def __str__(self):
        return f"{self.socio} en {self.sesion} ({self.get_estado_display()})"


class RegistroAcceso(models.Model):
    """Bitácora de cada lectura de QR en torniquete o kiosco. Es de solo lectura en el admin."""

    class Resultado(models.TextChoices):
        PERMITIDO = "PERMITIDO", "Permitido"
        DENEGADO = "DENEGADO", "Denegado"

    class Tipo(models.TextChoices):
        ENTRADA = "ENTRADA", "Entrada"
        SALIDA = "SALIDA", "Salida"

    socio = models.ForeignKey(
        Socio, null=True, blank=True, on_delete=models.SET_NULL, related_name="accesos"
    )
    token_leido = models.CharField(max_length=100)
    resultado = models.CharField(max_length=10, choices=Resultado.choices)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, blank=True)
    motivo = models.CharField(max_length=200)
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accesos_registrados",
    )

    class Meta:
        ordering = ["-fecha_hora"]
        verbose_name = "registro de acceso"
        verbose_name_plural = "registros de acceso"

    def __str__(self):
        return f"{self.get_resultado_display()} - {self.socio or self.token_leido}"
