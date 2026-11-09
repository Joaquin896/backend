from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views_api as v

router = DefaultRouter()
router.register("planes", v.PlanViewSet, basename="plan")
router.register("socios", v.SocioViewSet, basename="socio")
router.register("membresias", v.MembresiaViewSet, basename="membresia")
router.register("pagos", v.PagoViewSet, basename="pago")
router.register("clases", v.ClaseViewSet, basename="clase")
router.register("sesiones", v.SesionClaseViewSet, basename="sesion")
router.register("reservas", v.ReservaViewSet, basename="reserva")
router.register("accesos", v.RegistroAccesoViewSet, basename="acceso")

urlpatterns = [
    path("auth/token/", v.TokenView.as_view(), name="api-token"),
    path("auth/me/", v.MeView.as_view(), name="api-me"),
    path("acceso/validar/", v.ValidarAccesoView.as_view(), name="api-validar-acceso"),
    path("dashboard/aforo/", v.DashboardAforoView.as_view(), name="api-dashboard-aforo"),
] + router.urls
