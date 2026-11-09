from rest_framework import serializers

from . import services
from .models import Clase, Membresia, Pago, Plan, RegistroAcceso, Reserva, SesionClase, Socio


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "nombre", "descripcion", "precio", "duracion_dias", "activo"]


class SocioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Socio
        fields = [
            "id", "user", "documento", "nombre", "apellido", "email", "telefono",
            "qr_token", "en_instalaciones", "fecha_registro",
        ]
        read_only_fields = ["qr_token", "en_instalaciones", "fecha_registro"]


class MembresiaSerializer(serializers.ModelSerializer):
    """Lectura completa de una membresía."""

    estado_efectivo = serializers.SerializerMethodField()
    plan_nombre = serializers.CharField(source="plan.nombre", read_only=True)
    socio_nombre = serializers.SerializerMethodField()

    class Meta:
        model = Membresia
        fields = [
            "id", "socio", "socio_nombre", "plan", "plan_nombre", "fecha_inicio", "fecha_fin",
            "estado", "estado_efectivo", "congelada_desde", "dias_congelados", "creado_en",
        ]
        read_only_fields = fields

    def get_estado_efectivo(self, obj):
        return obj.estado_efectivo()

    def get_socio_nombre(self, obj):
        return str(obj.socio)


class MembresiaCrearSerializer(serializers.Serializer):
    """Creación de membresía: genera el registro y su pago inicial."""

    socio = serializers.PrimaryKeyRelatedField(queryset=Socio.objects.all())
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    fecha_inicio = serializers.DateField(required=False)
    metodo_pago = serializers.ChoiceField(choices=Pago.Metodo.choices, default=Pago.Metodo.EFECTIVO)
    referencia = serializers.CharField(required=False, allow_blank=True, max_length=60, default="")

    def create(self, validated):
        request = self.context.get("request")
        try:
            return services.registrar_membresia(
                socio=validated["socio"],
                plan=validated["plan"],
                fecha_inicio=validated.get("fecha_inicio"),
                metodo=validated["metodo_pago"],
                referencia=validated.get("referencia", ""),
                usuario=request.user if request else None,
            )
        except services.ReglaNegocioError as exc:
            raise serializers.ValidationError({"detail": str(exc)})


class MembresiaActualizarSerializer(serializers.ModelSerializer):
    """Corrección administrativa: solo permite ajustar la fecha de término."""

    class Meta:
        model = Membresia
        fields = ["fecha_fin"]

    def validate_fecha_fin(self, valor):
        if valor < self.instance.fecha_inicio:
            raise serializers.ValidationError("La fecha de término no puede ser anterior al inicio.")
        return valor


class PagoSerializer(serializers.ModelSerializer):
    registrado_por = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Pago
        fields = ["id", "membresia", "monto", "metodo", "referencia", "fecha_pago", "registrado_por"]


class ClaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Clase
        fields = ["id", "nombre", "instructor", "descripcion", "duracion_minutos", "capacidad", "activa"]


class SesionClaseSerializer(serializers.ModelSerializer):
    clase_nombre = serializers.CharField(source="clase.nombre", read_only=True)
    fin = serializers.DateTimeField(read_only=True)
    capacidad = serializers.IntegerField(required=False, min_value=1)
    cupos_disponibles = serializers.SerializerMethodField()

    class Meta:
        model = SesionClase
        fields = [
            "id", "clase", "clase_nombre", "inicio", "fin", "capacidad",
            "cupos_disponibles", "cancelada",
        ]

    def get_cupos_disponibles(self, obj):
        confirmadas = obj.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count()
        return max(obj.capacidad - confirmadas, 0)


class ReservaSerializer(serializers.ModelSerializer):
    """Lectura de reservas. La creación pasa por services.reservar_clase."""

    socio_nombre = serializers.SerializerMethodField()
    clase = serializers.CharField(source="sesion.clase.nombre", read_only=True)
    inicio = serializers.DateTimeField(source="sesion.inicio", read_only=True)

    def get_socio_nombre(self, obj):
        return str(obj.socio)

    class Meta:
        model = Reserva
        fields = [
            "id", "sesion", "socio", "socio_nombre", "clase", "inicio",
            "estado", "posicion_espera", "creada_en",
        ]
        read_only_fields = fields


class ReservaCrearSerializer(serializers.Serializer):
    sesion = serializers.PrimaryKeyRelatedField(queryset=SesionClase.objects.all())
    socio = serializers.PrimaryKeyRelatedField(queryset=Socio.objects.all(), required=False)


class RegistroAccesoSerializer(serializers.ModelSerializer):
    socio_nombre = serializers.SerializerMethodField()

    class Meta:
        model = RegistroAcceso
        fields = [
            "id", "socio", "socio_nombre", "token_leido", "resultado", "tipo",
            "motivo", "fecha_hora",
        ]
        read_only_fields = fields

    def get_socio_nombre(self, obj):
        return str(obj.socio) if obj.socio_id else None


class ValidarQRSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=100)
