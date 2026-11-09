"""Panel de administración de Django personalizado para FitLife."""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import services
from .models import Clase, Membresia, Pago, Plan, RegistroAcceso, Reserva, SesionClase, Socio

admin.site.site_header = "FitLife · Administración"
admin.site.site_title = "FitLife"
admin.site.index_title = "Gestión del centro deportivo"


# ---------------------------------------------------------------------------
# Planes y socios
# ---------------------------------------------------------------------------

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["nombre", "precio", "duracion_dias", "activo"]
    list_filter = ["activo"]
    list_editable = ["precio", "activo"]
    search_fields = ["nombre", "descripcion"]


class MembresiaInlineSocio(admin.TabularInline):
    model = Membresia
    extra = 0
    can_delete = False
    fields = ["plan", "fecha_inicio", "fecha_fin", "estado"]
    readonly_fields = ["plan", "fecha_inicio", "fecha_fin", "estado"]
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ["apellido", "nombre", "documento", "email", "telefono", "estado_membresia", "en_instalaciones"]
    list_filter = ["en_instalaciones", "fecha_registro"]
    search_fields = ["nombre", "apellido", "documento", "email"]
    readonly_fields = ["qr_token", "en_instalaciones", "fecha_registro"]
    autocomplete_fields = ["user"]
    inlines = [MembresiaInlineSocio]

    @admin.display(description="Membresía")
    def estado_membresia(self, obj):
        vigente = services.membresia_vigente(obj)
        if vigente:
            return f"Activa hasta {vigente.fecha_fin:%d/%m/%Y}"
        return services.motivo_sin_membresia(obj)


# ---------------------------------------------------------------------------
# Membresías y pagos
# ---------------------------------------------------------------------------

class MembresiaAdminForm(forms.ModelForm):
    metodo_pago = forms.ChoiceField(
        choices=Pago.Metodo.choices, initial=Pago.Metodo.EFECTIVO, label="Método de pago"
    )
    referencia = forms.CharField(required=False, max_length=60, label="Referencia de pago")

    class Meta:
        model = Membresia
        fields = ["socio", "plan", "fecha_inicio", "fecha_fin"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is None:
            socio, plan = cleaned.get("socio"), cleaned.get("plan")
            inicio = cleaned.get("fecha_inicio") or timezone.localdate()
            if socio and plan:
                try:
                    services.verificar_puede_contratar(socio, plan, inicio)
                except services.ReglaNegocioError as exc:
                    raise ValidationError(str(exc))
        return cleaned


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    """Alta mediante services.registrar_membresia (genera el pago). Cambios: solo fecha de término."""

    form = MembresiaAdminForm
    list_display = ["socio", "plan", "fecha_inicio", "fecha_fin", "estado", "estado_real"]
    list_filter = ["estado", "plan"]
    search_fields = ["socio__nombre", "socio__apellido", "socio__documento"]
    actions = ["congelar_seleccionadas", "descongelar_seleccionadas", "sincronizar_vencimientos"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["socio", "plan", "fecha_inicio", "metodo_pago", "referencia"]
        return ["socio", "plan", "fecha_inicio", "fecha_fin", "estado", "congelada_desde", "dias_congelados"]

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return []
        return ["socio", "plan", "fecha_inicio", "estado", "congelada_desde", "dias_congelados"]

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        creada = services.registrar_membresia(
            socio=form.cleaned_data["socio"],
            plan=form.cleaned_data["plan"],
            fecha_inicio=form.cleaned_data["fecha_inicio"],
            metodo=form.cleaned_data["metodo_pago"],
            referencia=form.cleaned_data["referencia"],
            usuario=request.user,
        )
        obj.pk = creada.pk
        obj.fecha_fin = creada.fecha_fin
        obj._state.adding = False

    @admin.display(description="Estado real")
    def estado_real(self, obj):
        return obj.estado_efectivo().label

    def _aplicar(self, request, queryset, funcion, mensaje):
        ok = 0
        for membresia in queryset:
            try:
                funcion(membresia)
                ok += 1
            except services.ReglaNegocioError as exc:
                self.message_user(request, f"{membresia}: {exc}", messages.WARNING)
        if ok:
            self.message_user(request, f"{ok} {mensaje}", messages.SUCCESS)

    @admin.action(description="Congelar membresías seleccionadas")
    def congelar_seleccionadas(self, request, queryset):
        self._aplicar(request, queryset, services.congelar_membresia, "membresía(s) congelada(s).")

    @admin.action(description="Descongelar membresías seleccionadas")
    def descongelar_seleccionadas(self, request, queryset):
        self._aplicar(request, queryset, services.descongelar_membresia, "membresía(s) reactivada(s).")

    @admin.action(description="Marcar como vencidas las membresías expiradas")
    def sincronizar_vencimientos(self, request, queryset):
        actualizadas = services.actualizar_estados_membresias()
        self.message_user(request, f"{actualizadas} membresía(s) marcadas como vencidas.", messages.SUCCESS)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["membresia", "monto", "metodo", "referencia", "fecha_pago", "registrado_por"]
    list_filter = ["metodo", "fecha_pago"]
    search_fields = ["referencia", "membresia__socio__nombre", "membresia__socio__apellido"]
    readonly_fields = ["registrado_por"]
    date_hierarchy = "fecha_pago"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.registrado_por = request.user
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Clases, sesiones y reservas
# ---------------------------------------------------------------------------

@admin.register(Clase)
class ClaseAdmin(admin.ModelAdmin):
    list_display = ["nombre", "instructor", "duracion_minutos", "capacidad", "activa"]
    list_filter = ["activa"]
    search_fields = ["nombre", "instructor"]


class ReservaInline(admin.TabularInline):
    model = Reserva
    extra = 0
    can_delete = False
    fields = ["socio", "estado", "posicion_espera"]
    readonly_fields = ["socio", "estado", "posicion_espera"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SesionClase)
class SesionClaseAdmin(admin.ModelAdmin):
    list_display = ["clase", "inicio", "capacidad", "confirmadas", "en_espera", "cancelada"]
    list_filter = ["cancelada", "clase", "inicio"]
    search_fields = ["clase__nombre"]
    date_hierarchy = "inicio"
    inlines = [ReservaInline]

    @admin.display(description="Confirmadas")
    def confirmadas(self, obj):
        return obj.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count()

    @admin.display(description="En espera")
    def en_espera(self, obj):
        return obj.reservas.filter(estado=Reserva.Estado.ESPERA).count()


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    """Las reservas se crean y cancelan desde la API/servicios para respetar cupos y lista de espera."""

    list_display = ["socio", "sesion", "estado", "posicion_espera", "creada_en"]
    list_filter = ["estado", "sesion__clase"]
    search_fields = ["socio__nombre", "socio__apellido"]
    actions = ["cancelar_reservas", "marcar_asistencia"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description="Cancelar reservas seleccionadas (ajusta lista de espera)")
    def cancelar_reservas(self, request, queryset):
        for reserva in queryset:
            try:
                services.cancelar_reserva(reserva)
            except services.ReglaNegocioError as exc:
                self.message_user(request, f"{reserva}: {exc}", messages.WARNING)

    @admin.action(description="Marcar asistencia de reservas confirmadas")
    def marcar_asistencia(self, request, queryset):
        for reserva in queryset:
            try:
                services.marcar_asistencia(reserva)
            except services.ReglaNegocioError as exc:
                self.message_user(request, f"{reserva}: {exc}", messages.WARNING)


# ---------------------------------------------------------------------------
# Bitácora de accesos (solo lectura)
# ---------------------------------------------------------------------------

@admin.register(RegistroAcceso)
class RegistroAccesoAdmin(admin.ModelAdmin):
    list_display = ["fecha_hora", "socio", "resultado", "tipo", "motivo"]
    list_filter = ["resultado", "tipo", "fecha_hora"]
    search_fields = ["socio__nombre", "socio__apellido", "token_leido", "motivo"]
    date_hierarchy = "fecha_hora"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
