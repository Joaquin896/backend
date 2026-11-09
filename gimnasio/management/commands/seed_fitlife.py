"""Carga datos de demostración (planes, clases, sesiones, socios y un usuario de recepción).

Uso:
    python manage.py seed_fitlife
    python manage.py seed_fitlife --password "clave-de-demo"
Si no se entrega contraseña, se genera una aleatoria y se imprime una sola vez.
"""

import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from gimnasio import services
from gimnasio.models import Clase, Plan, SesionClase, Socio

NOMBRES = [("Camila", "Rojas"), ("Matías", "Soto"), ("Valentina", "Pérez"), ("Diego", "Muñoz"), ("Fernanda", "Silva")]


class Command(BaseCommand):
    help = "Carga datos de demostración para FitLife."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Contraseña del usuario de recepción (opcional).")

    @transaction.atomic
    def handle(self, *args, **options):
        Usuario = get_user_model()
        password = options["password"] or secrets.token_urlsafe(10)

        recepcion, creado = Usuario.objects.get_or_create(
            username="recepcion", defaults={"is_staff": True, "email": ""}
        )
        if creado:
            recepcion.set_password(password)
            recepcion.save()
            self.stdout.write(f"Usuario de recepción creado: recepcion / {password}")
        else:
            self.stdout.write("El usuario 'recepcion' ya existía; no se cambió su contraseña.")

        basico, _ = Plan.objects.get_or_create(
            nombre="Básico 30 días", defaults={"precio": Decimal("25000"), "duracion_dias": 30}
        )
        Plan.objects.get_or_create(
            nombre="Premium 90 días", defaults={"precio": Decimal("65000"), "duracion_dias": 90}
        )

        spinning, _ = Clase.objects.get_or_create(
            nombre="Spinning",
            defaults={"instructor": "Javiera", "capacidad": 2, "duracion_minutos": 45},
        )
        yoga, _ = Clase.objects.get_or_create(
            nombre="Yoga",
            defaults={"instructor": "Tomás", "capacidad": 3, "duracion_minutos": 60},
        )

        ahora = timezone.localtime()
        for dias in range(0, 3):
            for clase, hora in ((spinning, 19), (yoga, 8)):
                inicio = (ahora + timedelta(days=dias)).replace(hour=hora, minute=0, second=0, microsecond=0)
                SesionClase.objects.get_or_create(clase=clase, inicio=inicio, defaults={"capacidad": clase.capacidad})

        for i, (nombre, apellido) in enumerate(NOMBRES, start=1):
            socio, _ = Socio.objects.get_or_create(
                documento=f"1{i}.000.00{i}-{i}",
                defaults={"nombre": nombre, "apellido": apellido, "email": f"{nombre.lower()}@ejemplo.cl"},
            )
            if not socio.membresias.exists():
                services.registrar_membresia(socio, basico, fecha_inicio=ahora.date())

        self.stdout.write(self.style.SUCCESS("Datos de demostración cargados."))
