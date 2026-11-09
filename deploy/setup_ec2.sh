#!/usr/bin/env bash
# Preparación de una instancia EC2 Ubuntu 22.04/24.04 para FitLife.
# Uso (en la instancia, como usuario ubuntu):
#   export POSTGRES_PASSWORD='una-clave-fuerte'
#   export REPO_URL='https://github.com/<usuario>/<repo>.git'
#   bash deploy/setup_ec2.sh
# Es repetible: si algo ya existe, lo reutiliza.
set -euo pipefail

: "${POSTGRES_PASSWORD:?Define POSTGRES_PASSWORD}"
APP_DIR="${APP_DIR:-$HOME/backend}"
REPO_URL="${REPO_URL:-}"

echo "==> Paquetes del sistema"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-dev build-essential \
    postgresql postgresql-contrib nginx git

echo "==> PostgreSQL: usuario y base de datos"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fitlife') THEN
    CREATE ROLE fitlife LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  ELSE
    ALTER ROLE fitlife WITH LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END \$\$;
SQL
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = 'fitlife'" | grep -q 1 \
  || sudo -u postgres createdb -O fitlife fitlife

echo "==> Código fuente"
if [ ! -d "$APP_DIR/.git" ] && [ -n "$REPO_URL" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> Entorno virtual y dependencias"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Archivo .env (revísalo y ajusta IP/DNS)"
if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(50))")
  sed -i "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=${SECRET}|" .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${POSTGRES_PASSWORD}|" .env
  sed -i "s|^DJANGO_DEBUG=.*|DJANGO_DEBUG=0|" .env
  echo "   .env creado. Edita DJANGO_ALLOWED_HOSTS y DJANGO_CSRF_TRUSTED_ORIGINS con tu IP pública."
fi

echo "==> Migraciones y archivos estáticos"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput

echo "==> Servicio systemd (Gunicorn)"
sudo cp deploy/fitlife.service /etc/systemd/system/fitlife.service
sudo sed -i "s|/home/ubuntu/backend|${APP_DIR}|g; s|User=ubuntu|User=${USER}|" /etc/systemd/system/fitlife.service
sudo systemctl daemon-reload
sudo systemctl enable --now fitlife

echo "==> Nginx como proxy público en el puerto 80"
sudo cp deploy/nginx.conf /etc/nginx/sites-available/fitlife
sudo ln -sf /etc/nginx/sites-available/fitlife /etc/nginx/sites-enabled/fitlife
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "Listo. Crea el usuario de recepción con: .venv/bin/python manage.py createsuperuser"
echo "o carga datos de demo con: .venv/bin/python manage.py seed_fitlife --password '<clave>'"
