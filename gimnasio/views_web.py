from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import services
from .models import Membresia, RegistroAcceso, Socio


class FitLifeLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class FitLifeLogoutView(LogoutView):
    next_page = "login"


@login_required
def inicio(request):
    if request.user.is_staff:
        return redirect("dashboard")
    return redirect("mi-cuenta")


@login_required
def dashboard(request):
    """Vista de control de aforo para recepción. Se actualiza sola consumiendo la API."""
    if not request.user.is_staff:
        return HttpResponseForbidden("Solo personal del centro.")
    return render(request, "gimnasio/dashboard.html")


@login_required
@require_http_methods(["GET", "POST"])
def simular_acceso(request):
    """Simulador de lectura de QR para pruebas en vivo (equivale al torniquete)."""
    if not request.user.is_staff:
        return HttpResponseForbidden("Solo personal del centro.")

    resultado = None
    if request.method == "POST":
        token = request.POST.get("token", "")
        resultado = services.registrar_acceso_qr(token, usuario=request.user)

    ultimos = RegistroAcceso.objects.select_related("socio").order_by("-fecha_hora")[:15]
    return render(request, "gimnasio/simular_acceso.html", {"resultado": resultado, "ultimos": ultimos})


@login_required
def clases(request):
    return render(request, "gimnasio/clases.html")


@login_required
def mi_cuenta(request):
    socio = Socio.objects.filter(user=request.user).first()
    membresia = services.membresia_vigente(socio) if socio else None
    ultima = Membresia.objects.filter(socio=socio).order_by("-fecha_fin").first() if socio else None
    return render(request, "gimnasio/mi_cuenta.html", {
        "socio": socio,
        "membresia": membresia,
        "ultima": ultima,
        "estado_ultima": ultima.estado_efectivo() if ultima else None,
    })
