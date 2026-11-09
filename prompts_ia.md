# Registro de apoyo de herramientas de IA

Proyecto: FitLife · Control de asistencia y reserva de clases
Herramienta: Claude (Claude Code, modo agente en repositorio)
Fecha de sesión: 2026-11-09

Este archivo registra las consultas y apoyos solicitados a la IA durante el desarrollo, según lo pedido en la evaluación. Las decisiones de diseño, la revisión del código y las pruebas en navegador fueron verificadas por el estudiante.

## Consultas realizadas

| # | Tema | Apoyo recibido | Qué se revisó / ajustó |
|---|---|---|---|
| 1 | Leer el enunciado del proyecto (FitLife) y la pauta de la evaluación, y construir la tarea descrita en ambos documentos. | Lectura de los requerimientos, propuesta de estructura Django + DRF con PostgreSQL y dominio en español (Plan, Socio, Membresia, Pago, Clase, SesionClase, Reserva, RegistroAcceso). | Se verificó que cada requerimiento de la rúbrica tuviera una implementación identificable (tabla en README.md). |
| 2 | Decisión de diseño (dentro de la tarea #1): reglas de acceso por QR: entrada/salida, membresía vigente, aforo máximo. | Propuesta de lectura que alterna ENTRADA/SALIDA, bloqueo consultivo de PostgreSQL para el aforo y registro de todas las denegaciones. | Pruebas de regresión en `gimnasio/tests/test_negocio.py`. |
| 3 | Decisión de diseño (dentro de la tarea #1): reservas con cupo y lista de espera automática. | Propuesta con `select_for_update` sobre la sesión, promoción del primero de la espera al cancelar y reordenamiento de posiciones. | Pruebas de cupo, promoción y reordenamiento. |
| 4 | Decisión de diseño (dentro de la tarea #1): dashboard de aforo en tiempo real sin WebSockets. | Endpoint `/api/dashboard/aforo/` y página que consulta cada 5 s, con render sin `innerHTML` para evitar inyección de texto. | Prueba en navegador headless (captura en móvil). |
| 5 | Decisión de diseño (dentro de la tarea #1): configuración para despliegue en EC2. | Scripts `deploy/setup_ec2.sh`, unidad systemd con Gunicorn y configuración de Nginx. | Pendiente de ejecución en AWS Academy por el estudiante. |

## Problemas detectados con apoyo de la IA y corregidos

- `socio_nombre` mostraba un texto técnico cuando el QR no pertenecía a ningún socio: se reemplazó por un campo calculado y se añadió prueba de regresión.
- Tras iniciar sesión, un socio era redirigido al dashboard de personal (403): ahora `LOGIN_REDIRECT_URL` pasa por la vista de inicio, que decide según el rol.
- En móvil, las tablas se cortaban sin indicación: se compactaron para teléfonos.

## Notas

- La única solicitud directa del estudiante fue la #1 (realizar la tarea de los documentos). Las filas 2 a 5 son decisiones de diseño tomadas por la IA dentro de esa tarea, no prompts separados.
- El estudiante debe agregar aquí, con el texto literal, cualquier otra consulta que haya hecho a una IA durante el desarrollo.
- No se copió código de terceros sin revisión. Las dependencias están fijadas en `requirements.txt`.
