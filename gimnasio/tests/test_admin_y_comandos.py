from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from gimnasio.models import Membresia, Plan, RegistroAcceso, Socio

Usuario = get_user_model()


class AdminTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_superuser("admin", "admin@ejemplo.cl", "clave-segura-123")
        self.client.force_login(self.admin)

    def test_paginas_de_listado_del_admin_cargan(self):
        for modelo in [Plan, Socio, Membresia, RegistroAcceso]:
            url = reverse(f"admin:gimnasio_{modelo._meta.model_name}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, modelo.__name__)

    def test_registro_de_acceso_es_solo_lectura(self):
        url = reverse("admin:gimnasio_registroacceso_add")
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_alta_de_membresia_desde_admin_genera_pago(self):
        plan = Plan.objects.create(nombre="Anual", precio=100000, duracion_dias=365)
        socio = Socio.objects.create(nombre="Gabriel", apellido="Toro", documento="9-9")
        respuesta = self.client.post(
            reverse("admin:gimnasio_membresia_add"),
            {"socio": socio.id, "plan": plan.id, "fecha_inicio": "2026-01-10",
             "metodo_pago": "EFECTIVO", "referencia": ""},
        )
        self.assertEqual(respuesta.status_code, 302)
        membresia = Membresia.objects.get(socio=socio)
        self.assertEqual(membresia.fecha_fin.isoformat(), "2027-01-09")  # 365 días, inicio inclusivo
        self.assertEqual(membresia.pagos.count(), 1)


class SeedTests(TestCase):
    def test_seed_es_idempotente(self):
        salida = StringIO()
        call_command("seed_fitlife", password="clave-demo-123", stdout=salida)
        call_command("seed_fitlife", password="clave-demo-123", stdout=salida)
        self.assertEqual(Socio.objects.count(), 5)
        self.assertEqual(Plan.objects.count(), 2)
