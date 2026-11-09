# FitLife · Control de asistencia y reserva de clases

Evaluación Parcial N°3 · Desarrollo Backend · Proyecto 2 (FitLife).

Aplicación Django + Django REST Framework con PostgreSQL. Cubre control de membresías, acceso por código QR, reserva de clases grupales con cupos y lista de espera automática, y un dashboard de aforo que se actualiza en vivo.

- **IP pública de AWS EC2:** `PENDIENTE: completar tras desplegar (ej. http://3.xx.xx.xx)`
- **Usuario de recepción de demostración:** `recepcion` (la clave la define quien ejecute `seed_fitlife`)
- **Prompts de IA:** ver [`prompts_ia.md`](prompts_ia.md)

## Requerimientos y dónde se cumplen

| Requerimiento del caso | Implementación |
|---|---|
| 1. CRUD de Planes, Pagos y Estados de Membresía (Activa, Vencida, Congelada) | `Plan`, `Pago`, `Membresia` (`gimnasio/models.py`). API en `/api/planes/`, `/api/pagos/`, `/api/membresias/` con acciones `congelar` y `descongelar`. Reglas en `gimnasio/services.py`. |
| 2. Validación y registro de acceso por QR | `POST /api/acceso/validar/` y simulador web `/acceso/simular/`. Cada socio tiene un `qr_token` UUID y `GET /api/socios/<id>/qr/` entrega el QR en SVG. Cada lectura queda en `RegistroAcceso`. |
| 3. Reserva de clases con cupos y lista de espera | `SesionClase` (cupo propio), `Reserva` (CONFIRMADA / ESPERA / CANCELADA / ASISTIO). Al cancelar, el primero de la lista pasa a confirmada y las posiciones se reordenan. |
| 4. Dashboard de aforo en tiempo real | `/dashboard/` (personal) consume `GET /api/dashboard/aforo/` cada 5 s: personas dentro, membresías por estado, ocupación de clases de hoy y últimos accesos. |
| Django Admin personalizado | `gimnasio/admin.py`: filtros, búsqueda, edición en lista, acciones masivas. Altas de membresía pasan por el servicio (generan el pago). Accesos y reservas son de solo lectura o se gestionan con acciones. |
| Seguridad, sesiones y roles | Token + sesión en la API; permisos `EsStaff`, `EsDuenoOStaff`; límites de tasa (`anon`, `user`, `acceso`, `login`); contraseñas validadas; cookies seguras configurables. |
| PostgreSQL y migraciones | `settings.py` usa solo PostgreSQL (sin fallback). Migraciones en `gimnasio/migrations/`. |
| Despliegue en EC2 | Scripts en `deploy/` (ver sección de despliegue). |

## Reglas de negocio principales

- **Vigencia:** una membresía dura `duracion_dias` del plan, incluyendo el día de inicio. No puede solaparse con otra vigente o congelada del mismo socio.
- **Vencida:** si la fecha de término ya pasó, la membresía se considera vencida aunque el campo aún diga `ACTIVA`. `python manage.py shell -c "from gimnasio.services import actualizar_estados_membresias as a; print(a())"` (o la acción del admin) la persiste.
- **Congelar:** solo membresías activas. Al descongelar, la fecha de término se extiende por los días congelados.
- **Acceso QR:** si el socio está dentro, la lectura registra una **salida**. Si no, se exige membresía activa y no se supera `FITLIFE_AFORO_MAXIMO`. Cada decisión queda registrada, también las denegadas.
- **Reservas:** requieren membresía activa, clase futura y no cancelada. Un socio no puede tener dos reservas activas para la misma sesión. Si la clase está llena, la reserva pasa a lista de espera. La concurrencia se controla con `select_for_update` (sesión) y un bloqueo consultivo de PostgreSQL al ingresar al centro.

## Estructura

```
fitlife/            configuración del proyecto (settings, urls, wsgi)
gimnasio/
  models.py         modelo de dominio
  services.py       reglas de negocio (membresías, acceso, reservas, dashboard)
  serializers.py    serialización y validación de la API
  views_api.py      endpoints REST
  views_web.py      vistas HTML (dashboard, simulador, clases, mi cuenta)
  admin.py          panel de administración personalizado
  permissions.py    roles y permisos
  exceptions.py     traducción de reglas de negocio a HTTP 400
  tests/            pruebas de reglas, API, admin y comandos
  management/commands/seed_fitlife.py   datos de demostración
deploy/             script de preparación EC2, unidad systemd y nginx
prompts_ia.md       registro de apoyo de herramientas de IA
```

## Ejecución local

Requisitos: Python 3.12+ y PostgreSQL 14+.

```bash
# 1. Base de datos
sudo -u postgres psql -c "CREATE ROLE fitlife LOGIN PASSWORD 'cambia-esta-clave';"
sudo -u postgres createdb -O fitlife fitlife

# 2. Entorno Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configuración
cp .env.example .env          # edita POSTGRES_PASSWORD, DJANGO_SECRET_KEY, etc.

# 4. Migraciones y datos de prueba
python manage.py migrate
python manage.py seed_fitlife --password 'clave-demo-2026'

# 5. Servidor
python manage.py runserver
```

Para pruebas en modo local sin HTTPS, pon `DJANGO_DEBUG=1` en `.env`.

Luego abre http://127.0.0.1:8000/ e ingresa como `recepcion`. Un socio de ejemplo puede tener un usuario propio creándolo en el admin y vinculándolo a su ficha.

### Pruebas

```bash
python manage.py test gimnasio -v 2
```

Las pruebas usan la base de datos de PostgreSQL (se crea una base temporal).

## API (resumen)

Autenticación: `POST /api/auth/token/` con `username` y `password` devuelve un token. Úsalo como `Authorization: Token <token>`. También funciona la sesión del navegador.

| Método y ruta | Quién | Descripción |
|---|---|---|
| `GET /api/auth/me/` | Cualquier autenticado | Usuario, rol y membresía vigente |
| `GET/POST /api/planes/` · `GET/PUT/PATCH/DELETE /api/planes/<id>/` | Lectura: autenticados · Escritura: staff | Planes |
| `GET/POST /api/socios/` · `GET/PUT/PATCH/DELETE /api/socios/<id>/` · `GET /api/socios/<id>/qr/` | Socio ve solo su ficha; staff ve todo | Socios y QR (SVG) |
| `GET/POST /api/membresias/` · `GET/PATCH /api/membresias/<id>/` · `POST .../congelar/` · `POST .../descongelar/` | Socio ve las suyas; escritura: staff | Membresías (no se borran: quedan como historial) |
| `GET/POST/PUT/PATCH/DELETE /api/pagos/` | Staff | Pagos |
| `GET/POST/... /api/clases/` | Lectura: autenticados · Escritura: staff | Definición de clases (Spinning, Yoga…) |
| `GET/POST/... /api/sesiones/` | Socio ve sesiones futuras; staff ve todo | Sesiones con cupo y `cupos_disponibles` |
| `GET /api/reservas/` · `POST /api/reservas/` · `POST .../cancelar/` · `POST .../asistencia/` | Socio: propias · Staff: todas | Reservas, lista de espera, asistencia |
| `POST /api/acceso/validar/` | Staff (kiosco) | Body `{"token": "<uuid>"}`. Responde 200 si permite y 403 si deniega |
| `GET /api/accesos/` | Staff | Bitácora de accesos |
| `GET /api/dashboard/aforo/` | Staff | Resumen en vivo del aforo |

Ejemplo de lectura de QR:

```bash
curl -X POST http://127.0.0.1:8000/api/acceso/validar/ \
  -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  -d '{"token": "99a5e16a-f7b3-43af-8185-c68a998a85c4"}'
```

## Despliegue en AWS EC2 (instancia única)

Estos pasos los ejecuta el estudiante en AWS Academy. Se incluyen scripts para hacerlos repetibles.

1. Lanza una instancia Ubuntu 22.04/24.04 (t2.micro o t3.micro) con un grupo de seguridad que permita **22** (SSH), **80** (HTTP) y, si se usa, **443**. Asigna una **IP elástica** para que la IP pública no cambie.
2. Conéctate por SSH y ejecuta:

```bash
export POSTGRES_PASSWORD='una-clave-fuerte'
export REPO_URL='https://github.com/<usuario>/<repo>.git'
git clone "$REPO_URL" ~/backend && cd ~/backend
bash deploy/setup_ec2.sh
```

3. Edita `~/backend/.env` y pon tu IP en:

```
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<IP_PUBLICA>
DJANGO_CSRF_TRUSTED_ORIGINS=http://<IP_PUBLICA>
```

Luego reinicia: `sudo systemctl restart fitlife`.

4. Crea el usuario de recepción: `.venv/bin/python manage.py createsuperuser` o `seed_fitlife --password ...`.
5. Verifica: `http://<IP_PUBLICA>/` debe mostrar la pantalla de ingreso, y `http://<IP_PUBLICA>/admin/` el panel de administración.

Servicios útiles: `sudo systemctl status fitlife`, `sudo journalctl -u fitlife -n 100`, `sudo systemctl status nginx`.

## Limitaciones conocidas

- El dashboard se actualiza por **consulta periódica** (cada 5 s), no por WebSockets.
- Los socios de la lista de espera **no reciben notificación** automática al liberarse un cupo; quedan confirmados y lo ven en su página de clases.
- Sin HTTPS configurado en la entrega. Activa `DJANGO_SECURE_COOKIES=1` solo cuando haya certificado.
- El simulador de QR reemplaza al lector físico; la API está lista para que un torniquete la consuma.
