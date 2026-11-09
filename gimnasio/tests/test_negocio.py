from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from gimnasio import services
from gimnasio.models import Membresia, Pago, RegistroAcceso, Reserva
from gimnasio.tests.base import crear_clase, crear_plan, crear_sesion, crear_socio, hoy


class MembresiasTests(TestCase):
    def setUp(self):
        self.plan = crear_plan(dias=30, precio="25000")
        self.socio = crear_socio("Luis")

    def test_registrar_membresia_calcula_fin_y_genera_pago(self):
        m = services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy())
        self.assertEqual(m.fecha_fin, hoy() + timedelta(days=29))
        self.assertEqual(m.estado, Membresia.Estado.ACTIVA)
        pago = Pago.objects.get(membresia=m)
        self.assertEqual(pago.monto, self.plan.precio)

    def test_no_permite_dos_membresias_solapadas(self):
        services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy())
        with self.assertRaises(services.ReglaNegocioError):
            services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy() + timedelta(days=5))

    def test_no_vende_planes_inactivos(self):
        inactivo = crear_plan(nombre="Antiguo", activo=False)
        with self.assertRaises(services.ReglaNegocioError):
            services.registrar_membresia(self.socio, inactivo)

    def test_congelar_y_descongelar_extiende_la_vigencia(self):
        m = services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy())
        fin_original = m.fecha_fin
        services.congelar_membresia(m)
        m.refresh_from_db()
        self.assertEqual(m.estado, Membresia.Estado.CONGELADA)

        Membresia.objects.filter(pk=m.pk).update(congelada_desde=hoy() - timedelta(days=4))
        services.descongelar_membresia(m)
        m.refresh_from_db()
        self.assertEqual(m.estado, Membresia.Estado.ACTIVA)
        self.assertEqual(m.dias_congelados, 4)
        self.assertEqual(m.fecha_fin, fin_original + timedelta(days=4))

    def test_no_congela_una_membresia_vencida(self):
        m = services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy() - timedelta(days=60))
        with self.assertRaises(services.ReglaNegocioError):
            services.congelar_membresia(m)

    def test_estado_efectivo_detecta_vencimiento_sin_sincronizar(self):
        m = services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy() - timedelta(days=40))
        self.assertEqual(m.estado_efectivo(), Membresia.Estado.VENCIDA)
        self.assertEqual(services.actualizar_estados_membresias(), 1)
        m.refresh_from_db()
        self.assertEqual(m.estado, Membresia.Estado.VENCIDA)


class AccesoQRTests(TestCase):
    def setUp(self):
        self.plan = crear_plan()
        self.socio = crear_socio("Marta")
        services.registrar_membresia(self.socio, self.plan, fecha_inicio=hoy())

    def test_token_invalido_se_deniega(self):
        registro = services.registrar_acceso_qr("no-es-uuid")
        self.assertEqual(registro.resultado, RegistroAcceso.Resultado.DENEGADO)
        self.assertEqual(registro.motivo, "QR no válido")

    def test_token_desconocido_se_deniega(self):
        registro = services.registrar_acceso_qr("3f1c2a5e-0000-4000-8000-000000000000")
        self.assertEqual(registro.motivo, "QR no reconocido")

    def test_entrada_y_luego_salida_con_el_mismo_qr(self):
        entrada = services.registrar_acceso_qr(str(self.socio.qr_token))
        self.assertEqual(entrada.resultado, RegistroAcceso.Resultado.PERMITIDO)
        self.assertEqual(entrada.tipo, RegistroAcceso.Tipo.ENTRADA)
        self.socio.refresh_from_db()
        self.assertTrue(self.socio.en_instalaciones)

        salida = services.registrar_acceso_qr(str(self.socio.qr_token))
        self.assertEqual(salida.tipo, RegistroAcceso.Tipo.SALIDA)
        self.socio.refresh_from_db()
        self.assertFalse(self.socio.en_instalaciones)

    def test_socio_sin_membresia_no_entra(self):
        sin_plan = crear_socio("Sin")
        registro = services.registrar_acceso_qr(str(sin_plan.qr_token))
        self.assertEqual(registro.resultado, RegistroAcceso.Resultado.DENEGADO)
        self.assertEqual(registro.motivo, "Sin membresía registrada")

    def test_membresia_vencida_no_entra(self):
        vencido = crear_socio("Vencido")
        services.registrar_membresia(vencido, self.plan, fecha_inicio=hoy() - timedelta(days=60))
        registro = services.registrar_acceso_qr(str(vencido.qr_token))
        self.assertEqual(registro.motivo, "Membresía vencida")

    def test_membresia_congelada_no_entra(self):
        congelado = crear_socio("Congelado")
        m = services.registrar_membresia(congelado, self.plan, fecha_inicio=hoy())
        services.congelar_membresia(m)
        registro = services.registrar_acceso_qr(str(congelado.qr_token))
        self.assertEqual(registro.motivo, "Membresía congelada")

    @override_settings(FITLIFE_AFORO_MAXIMO=1)
    def test_no_supera_el_aforo_maximo(self):
        services.registrar_acceso_qr(str(self.socio.qr_token))  # ocupa el único cupo
        otro = crear_socio("Otro")
        services.registrar_membresia(otro, self.plan, fecha_inicio=hoy())
        registro = services.registrar_acceso_qr(str(otro.qr_token))
        self.assertEqual(registro.resultado, RegistroAcceso.Resultado.DENEGADO)
        self.assertEqual(registro.motivo, "Aforo máximo alcanzado")

    def test_resumen_dashboard_cuenta_personas_dentro(self):
        services.registrar_acceso_qr(str(self.socio.qr_token))
        resumen = services.resumen_dashboard()
        self.assertEqual(resumen["aforo"]["personas_dentro"], 1)
        self.assertEqual(resumen["membresias"]["vigentes"], 1)


class ReservasTests(TestCase):
    def setUp(self):
        self.plan = crear_plan()
        self.clase = crear_clase(capacidad=2)
        self.sesion = crear_sesion(self.clase)
        self.socios = []
        for nombre in ["Ana", "Beto", "Carla", "Diego"]:
            s = crear_socio(nombre)
            services.registrar_membresia(s, self.plan, fecha_inicio=hoy())
            self.socios.append(s)

    def test_confirma_hasta_capacidad_y_luego_lista_de_espera(self):
        r1 = services.reservar_clase(self.socios[0], self.sesion)
        r2 = services.reservar_clase(self.socios[1], self.sesion)
        r3 = services.reservar_clase(self.socios[2], self.sesion)
        r4 = services.reservar_clase(self.socios[3], self.sesion)
        self.assertEqual(r1.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual(r2.estado, Reserva.Estado.CONFIRMADA)
        self.assertEqual((r3.estado, r3.posicion_espera), (Reserva.Estado.ESPERA, 1))
        self.assertEqual((r4.estado, r4.posicion_espera), (Reserva.Estado.ESPERA, 2))

    def test_cancelar_confirmada_promueve_primero_de_la_espera(self):
        r1 = services.reservar_clase(self.socios[0], self.sesion)
        services.reservar_clase(self.socios[1], self.sesion)
        r3 = services.reservar_clase(self.socios[2], self.sesion)
        r4 = services.reservar_clase(self.socios[3], self.sesion)

        services.cancelar_reserva(r1)

        r3.refresh_from_db()
        r4.refresh_from_db()
        self.assertEqual(r3.estado, Reserva.Estado.CONFIRMADA)
        self.assertIsNone(r3.posicion_espera)
        self.assertEqual((r4.estado, r4.posicion_espera), (Reserva.Estado.ESPERA, 1))

    def test_cancelar_en_espera_reordena_posiciones(self):
        services.reservar_clase(self.socios[0], self.sesion)
        services.reservar_clase(self.socios[1], self.sesion)
        r3 = services.reservar_clase(self.socios[2], self.sesion)
        r4 = services.reservar_clase(self.socios[3], self.sesion)

        services.cancelar_reserva(r3)

        r4.refresh_from_db()
        self.assertEqual(r4.posicion_espera, 1)
        self.assertEqual(self.sesion.reservas.filter(estado=Reserva.Estado.CONFIRMADA).count(), 2)

    def test_no_duplica_reserva_del_mismo_socio(self):
        services.reservar_clase(self.socios[0], self.sesion)
        with self.assertRaises(services.ReglaNegocioError):
            services.reservar_clase(self.socios[0], self.sesion)

    def test_reactiva_reserva_cancelada_sin_duplicar_fila(self):
        r = services.reservar_clase(self.socios[0], self.sesion)
        services.cancelar_reserva(r)
        again = services.reservar_clase(self.socios[0], self.sesion)
        self.assertEqual(again.pk, r.pk)
        self.assertEqual(again.estado, Reserva.Estado.CONFIRMADA)

    def test_requiere_membresia_vigente(self):
        sin = crear_socio("SinPlan")
        with self.assertRaises(services.ReglaNegocioError):
            services.reservar_clase(sin, self.sesion)

    def test_no_reserva_clases_pasadas(self):
        pasada = crear_sesion(self.clase, horas_desde_ahora=-2)
        with self.assertRaises(services.ReglaNegocioError):
            services.reservar_clase(self.socios[0], pasada)

    def test_no_reserva_sesiones_canceladas(self):
        self.sesion.cancelada = True
        self.sesion.save()
        with self.assertRaises(services.ReglaNegocioError):
            services.reservar_clase(self.socios[0], self.sesion)

    def test_capacidad_por_defecto_viene_de_la_clase(self):
        self.assertEqual(self.sesion.capacidad, self.clase.capacidad)
        self.assertLess(timezone.now(), self.sesion.inicio)
        self.assertEqual(self.sesion.fin - self.sesion.inicio, timedelta(minutes=45))
