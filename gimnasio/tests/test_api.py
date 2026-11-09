from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from gimnasio import services
from gimnasio.models import Membresia, Pago, Reserva
from gimnasio.tests.base import crear_clase, crear_plan, crear_sesion, crear_socio, hoy

Usuario = get_user_model()


class ApiBase(TestCase):
    def setUp(self):
        self.staff = Usuario.objects.create_user("recepcion", password="clave-segura-123", is_staff=True)
        self.plan = crear_plan()
        self.socio_a = crear_socio("Ana", con_usuario=True)
        self.socio_b = crear_socio("Beto", con_usuario=True)
        services.registrar_membresia(self.socio_a, self.plan, fecha_inicio=hoy())
        services.registrar_membresia(self.socio_b, self.plan, fecha_inicio=hoy())
        self.cliente_staff = self._cliente(self.staff)
        self.cliente_a = self._cliente(self.socio_a.user)
        self.cliente_b = self._cliente(self.socio_b.user)

    def _cliente(self, usuario):
        cliente = APIClient()
        token, _ = Token.objects.get_or_create(user=usuario)
        cliente.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return cliente


class PermisosTests(ApiBase):
    def test_sin_autenticacion_no_hay_acceso(self):
        respuesta = APIClient().get("/api/socios/")
        self.assertEqual(respuesta.status_code, 401)

    def test_socio_no_puede_crear_planes(self):
        respuesta = self.cliente_a.post("/api/planes/", {"nombre": "Pro", "precio": "1", "duracion_dias": 30}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    def test_staff_puede_crear_planes(self):
        respuesta = self.cliente_staff.post("/api/planes/", {"nombre": "Pro", "precio": "30000", "duracion_dias": 30}, format="json")
        self.assertEqual(respuesta.status_code, 201)

    def test_socio_solo_ve_sus_propias_membresias(self):
        respuesta = self.cliente_a.get("/api/membresias/")
        self.assertEqual(respuesta.status_code, 200)
        socios = {m["socio"] for m in respuesta.json()["results"]}
        self.assertEqual(socios, {self.socio_a.id})

    def test_socio_no_puede_reservar_por_otro(self):
        sesion = crear_sesion(crear_clase())
        respuesta = self.cliente_a.post(
            "/api/reservas/", {"sesion": sesion.id, "socio": self.socio_b.id}, format="json"
        )
        self.assertEqual(respuesta.status_code, 403)

    def test_dashboard_solo_para_staff(self):
        self.assertEqual(self.cliente_a.get("/api/dashboard/aforo/").status_code, 403)
        self.assertEqual(self.cliente_staff.get("/api/dashboard/aforo/").status_code, 200)

    def test_validar_acceso_solo_para_staff(self):
        respuesta = self.cliente_a.post("/api/acceso/validar/", {"token": str(self.socio_a.qr_token)}, format="json")
        self.assertEqual(respuesta.status_code, 403)

    def test_web_dashboard_bloquea_socios(self):
        self.client.force_login(self.socio_a.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)


class AccesoApiTests(ApiBase):
    def test_qr_permitido_responde_200(self):
        respuesta = self.cliente_staff.post("/api/acceso/validar/", {"token": str(self.socio_a.qr_token)}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["resultado"], "PERMITIDO")
        self.assertEqual(respuesta.json()["tipo"], "ENTRADA")

    def test_qr_denegado_responde_403(self):
        respuesta = self.cliente_staff.post("/api/acceso/validar/", {"token": "basura"}, format="json")
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(respuesta.json()["resultado"], "DENEGADO")

    def test_registro_sin_socio_muestra_nombre_nulo(self):
        respuesta = self.cliente_staff.post("/api/acceso/validar/", {"token": "basura"}, format="json")
        self.assertIsNone(respuesta.json()["socio_nombre"])

    def test_qr_del_socio_devuelve_svg(self):
        respuesta = self.cliente_a.get(f"/api/socios/{self.socio_a.id}/qr/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", respuesta.content)

    def test_socio_no_puede_ver_qr_ajeno(self):
        respuesta = self.cliente_a.get(f"/api/socios/{self.socio_b.id}/qr/")
        self.assertEqual(respuesta.status_code, 404)


class MembresiaApiTests(ApiBase):
    def test_crear_membresia_por_api_genera_pago(self):
        nuevo = crear_socio("Carla")
        respuesta = self.cliente_staff.post(
            "/api/membresias/",
            {"socio": nuevo.id, "plan": self.plan.id, "metodo_pago": "TARJETA", "referencia": "AUT-1"},
            format="json",
        )
        self.assertEqual(respuesta.status_code, 201)
        membresia = Membresia.objects.get(socio=nuevo)
        self.assertEqual(Pago.objects.get(membresia=membresia).metodo, "TARJETA")

    def test_crear_membresia_solapada_responde_400(self):
        respuesta = self.cliente_staff.post(
            "/api/membresias/", {"socio": self.socio_a.id, "plan": self.plan.id}, format="json"
        )
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("detail", respuesta.json())

    def test_congelar_y_descongelar_por_api(self):
        m = Membresia.objects.get(socio=self.socio_a)
        r = self.cliente_staff.post(f"/api/membresias/{m.id}/congelar/")
        self.assertEqual(r.json()["estado"], "CONGELADA")
        r = self.cliente_staff.post(f"/api/membresias/{m.id}/descongelar/")
        self.assertEqual(r.json()["estado"], "ACTIVA")

    def test_no_se_pueden_borrar_membresias(self):
        m = Membresia.objects.get(socio=self.socio_a)
        respuesta = self.cliente_staff.delete(f"/api/membresias/{m.id}/")
        self.assertEqual(respuesta.status_code, 405)


class ReservaApiTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.clase = crear_clase(capacidad=1)
        self.sesion = crear_sesion(self.clase)

    def test_socio_reserva_y_cancela_su_cupo(self):
        r = self.cliente_a.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["estado"], "CONFIRMADA")
        reserva_id = r.json()["id"]

        r = self.cliente_a.post(f"/api/reservas/{reserva_id}/cancelar/")
        self.assertEqual(r.json()["estado"], "CANCELADA")

    def test_segundo_socio_queda_en_espera_por_api(self):
        self.cliente_a.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        r = self.cliente_b.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["estado"], "ESPERA")
        self.assertEqual(r.json()["posicion_espera"], 1)

    def test_socio_no_puede_cancelar_reserva_ajena(self):
        r = self.cliente_a.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        ajena = r.json()["id"]
        respuesta = self.cliente_b.post(f"/api/reservas/{ajena}/cancelar/")
        self.assertEqual(respuesta.status_code, 404)

    def test_asistencia_solo_staff(self):
        r = self.cliente_a.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        reserva_id = r.json()["id"]
        self.assertEqual(self.cliente_a.post(f"/api/reservas/{reserva_id}/asistencia/").status_code, 403)
        r = self.cliente_staff.post(f"/api/reservas/{reserva_id}/asistencia/")
        self.assertEqual(r.json()["estado"], "ASISTIO")
        self.assertEqual(Reserva.objects.get(pk=reserva_id).estado, Reserva.Estado.ASISTIO)

    def test_sin_membresia_responde_400_con_detalle(self):
        sin = crear_socio("Sinplan", con_usuario=True)
        cliente = self._cliente(sin.user)
        r = cliente.post("/api/reservas/", {"sesion": self.sesion.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("membresía", r.json()["detail"])


class WebTests(ApiBase):
    def test_inicio_redirige_al_login_si_no_hay_sesion(self):
        respuesta = self.client.get("/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/accounts/login/", respuesta["Location"])

    def test_login_de_socio_redirige_a_mi_cuenta(self):
        respuesta = self.client.post(reverse("login"), {"username": self.socio_a.user.username, "password": "clave-segura-123"}, follow=True)
        self.assertEqual(respuesta.redirect_chain[-1][0], reverse("mi-cuenta"))

    def test_login_de_staff_redirige_a_dashboard(self):
        respuesta = self.client.post(reverse("login"), {"username": "recepcion", "password": "clave-segura-123"}, follow=True)
        self.assertEqual(respuesta.redirect_chain[-1][0], reverse("dashboard"))

    def test_staff_ve_el_dashboard(self):
        self.client.force_login(self.staff)
        respuesta = self.client.get(reverse("dashboard"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Control de aforo")

    def test_simulador_registra_acceso(self):
        self.client.force_login(self.staff)
        respuesta = self.client.post(reverse("simular-acceso"), {"token": str(self.socio_a.qr_token)})
        self.assertContains(respuesta, "Permitido")
