import io

import segno
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .models import Clase, Membresia, Pago, Plan, RegistroAcceso, Reserva, SesionClase, Socio
from .permissions import EsStaff, StaffEscribeOLecturaAutenticada
from .serializers import (
    ClaseSerializer,
    MembresiaActualizarSerializer,
    MembresiaCrearSerializer,
    MembresiaSerializer,
    PagoSerializer,
    PlanSerializer,
    RegistroAccesoSerializer,
    ReservaCrearSerializer,
    ReservaSerializer,
    SesionClaseSerializer,
    SocioSerializer,
    ValidarQRSerializer,
)

ESCRITURA = ("create", "update", "partial_update", "destroy")


class PlanViewSet(viewsets.ModelViewSet):
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [StaffEscribeOLecturaAutenticada]


class SocioViewSet(viewsets.ModelViewSet):
    serializer_class = SocioSerializer

    def get_permissions(self):
        if self.action in ESCRITURA:
            return [IsAuthenticated(), EsStaff()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = Socio.objects.select_related("user")
        usuario = self.request.user
        if not usuario.is_staff:
            qs = qs.filter(user=usuario)
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(apellido__icontains=q) | Q(documento__icontains=q))
        return qs

    @action(detail=True, methods=["get"], url_path="qr")
    def qr(self, request, pk=None):
        """Imagen SVG con el QR del socio (lo que el torniquete debe leer)."""
        socio = self.get_object()
        buffer = io.BytesIO()
        segno.make(str(socio.qr_token), error="m").save(buffer, kind="svg", scale=8, border=2)
        return HttpResponse(buffer.getvalue(), content_type="image/svg+xml")


class MembresiaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Las membresías no se borran (quedan como historial); se congelan, vencen o corrigen."""

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "congelar", "descongelar"):
            return [IsAuthenticated(), EsStaff()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "create":
            return MembresiaCrearSerializer
        if self.action in ("update", "partial_update"):
            return MembresiaActualizarSerializer
        return MembresiaSerializer

    def get_queryset(self):
        qs = Membresia.objects.select_related("socio", "plan")
        usuario = self.request.user
        if not usuario.is_staff:
            qs = qs.filter(socio__user=usuario)
        estado = self.request.query_params.get("estado")
        if estado:
            qs = qs.filter(estado=estado.upper())
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        membresia = serializer.save()
        return Response(MembresiaSerializer(membresia).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def congelar(self, request, pk=None):
        membresia = services.congelar_membresia(self.get_object())
        return Response(MembresiaSerializer(membresia).data)

    @action(detail=True, methods=["post"])
    def descongelar(self, request, pk=None):
        membresia = services.descongelar_membresia(self.get_object())
        return Response(MembresiaSerializer(membresia).data)


class PagoViewSet(viewsets.ModelViewSet):
    queryset = Pago.objects.select_related("membresia__socio").all()
    serializer_class = PagoSerializer
    permission_classes = [IsAuthenticated, EsStaff]

    def perform_create(self, serializer):
        serializer.save(registrado_por=self.request.user)


class ClaseViewSet(viewsets.ModelViewSet):
    queryset = Clase.objects.all()
    serializer_class = ClaseSerializer
    permission_classes = [StaffEscribeOLecturaAutenticada]


class SesionClaseViewSet(viewsets.ModelViewSet):
    serializer_class = SesionClaseSerializer
    permission_classes = [StaffEscribeOLecturaAutenticada]

    def get_queryset(self):
        qs = SesionClase.objects.select_related("clase")
        if not self.request.user.is_staff:
            # Socios: solo clases vigentes desde hoy en adelante
            inicio_dia = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
            qs = qs.filter(cancelada=False, inicio__gte=inicio_dia)
        return qs


class ReservaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ReservaCrearSerializer if self.action == "create" else ReservaSerializer

    def get_queryset(self):
        qs = Reserva.objects.select_related("socio", "sesion__clase")
        usuario = self.request.user
        if not usuario.is_staff:
            qs = qs.filter(socio__user=usuario)
        sesion = self.request.query_params.get("sesion")
        if sesion:
            qs = qs.filter(sesion_id=sesion)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = ReservaCrearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sesion = serializer.validated_data["sesion"]
        socio = serializer.validated_data.get("socio")

        if socio is None:
            socio = Socio.objects.filter(user=request.user).first()
            if socio is None:
                return Response(
                    {"detail": "Tu usuario no tiene un perfil de socio asociado."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif not request.user.is_staff and socio.user_id != request.user.id:
            return Response(
                {"detail": "Solo puedes reservar para ti mismo."},
                status=status.HTTP_403_FORBIDDEN,
            )

        reserva = services.reservar_clase(socio, sesion)
        return Response(ReservaSerializer(reserva).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        reserva = services.cancelar_reserva(self.get_object())
        return Response(ReservaSerializer(reserva).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, EsStaff])
    def asistencia(self, request, pk=None):
        reserva = services.marcar_asistencia(self.get_object())
        return Response(ReservaSerializer(reserva).data)


class RegistroAccesoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = RegistroAcceso.objects.select_related("socio").all()
    serializer_class = RegistroAccesoSerializer
    permission_classes = [IsAuthenticated, EsStaff]

    def get_queryset(self):
        qs = super().get_queryset()
        resultado = self.request.query_params.get("resultado")
        if resultado:
            qs = qs.filter(resultado=resultado.upper())
        return qs


class ValidarAccesoView(APIView):
    """Endpoint que usa el torniquete/kiosco: recibe el contenido del QR y decide el paso."""

    permission_classes = [IsAuthenticated, EsStaff]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "acceso"

    def post(self, request):
        entrada = ValidarQRSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        registro = services.registrar_acceso_qr(entrada.validated_data["token"], usuario=request.user)
        datos = RegistroAccesoSerializer(registro).data
        codigo = status.HTTP_200_OK if registro.resultado == RegistroAcceso.Resultado.PERMITIDO else status.HTTP_403_FORBIDDEN
        return Response(datos, status=codigo)


class DashboardAforoView(APIView):
    permission_classes = [IsAuthenticated, EsStaff]

    def get(self, request):
        return Response(services.resumen_dashboard())


class TokenView(ObtainAuthToken):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        socio = Socio.objects.filter(user=usuario).first()
        vigente = services.membresia_vigente(socio) if socio else None
        return Response({
            "id": usuario.id,
            "username": usuario.username,
            "es_staff": usuario.is_staff,
            "socio_id": socio.id if socio else None,
            "membresia_vigente": {
                "plan": vigente.plan.nombre,
                "fecha_fin": vigente.fecha_fin,
            } if vigente else None,
        })
