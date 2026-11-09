from django.urls import path

from . import views_web as v

urlpatterns = [
    path("", v.inicio, name="inicio"),
    path("accounts/login/", v.FitLifeLoginView.as_view(), name="login"),
    path("accounts/logout/", v.FitLifeLogoutView.as_view(), name="logout"),
    path("dashboard/", v.dashboard, name="dashboard"),
    path("acceso/simular/", v.simular_acceso, name="simular-acceso"),
    path("clases/", v.clases, name="clases"),
    path("mi-cuenta/", v.mi_cuenta, name="mi-cuenta"),
]
