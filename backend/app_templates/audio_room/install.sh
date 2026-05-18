#!/bin/bash
# {{APP_NAME}} — instalador para VPS Ubuntu/Debian
# Uso: curl -fsSL https://raw.githubusercontent.com/TU-USUARIO/TU-REPO/main/install.sh | bash
# o:   chmod +x install.sh && sudo ./install.sh

set -e

echo "=========================================="
echo "  Instalador {{APP_NAME}} para VPS"
echo "=========================================="

# 1. Dependencias del sistema
echo "[1/6] Instalando dependencias..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 2. Clonar el repo si no existe
if [ ! -d "/opt/{{APP_NAME_SLUG}}" ]; then
  echo "[2/6] Cloná tu repo a /opt/{{APP_NAME_SLUG}} primero:"
  echo "  cd /opt && git clone https://github.com/TU-USUARIO/TU-REPO {{APP_NAME_SLUG}}"
  echo "  Luego volvé a correr este script."
  exit 1
fi

cd /opt/{{APP_NAME_SLUG}}/backend

# 3. Virtualenv
echo "[3/6] Creando entorno virtual..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. JWT_SECRET random si no existe el .env
if [ ! -f .env ]; then
  echo "[4/6] Generando .env con JWT_SECRET random..."
  echo "JWT_SECRET=$(openssl rand -hex 32)" > .env
  echo "PORT=8001" >> .env
fi

# 5. Crear systemd service
echo "[5/6] Configurando systemd..."
sudo tee /etc/systemd/system/{{APP_NAME_SLUG}}.service > /dev/null <<EOF
[Unit]
Description={{APP_NAME}} (Lluvia App Studio)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/{{APP_NAME_SLUG}}/backend
EnvironmentFile=/opt/{{APP_NAME_SLUG}}/backend/.env
ExecStart=/opt/{{APP_NAME_SLUG}}/backend/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable {{APP_NAME_SLUG}}
sudo systemctl start {{APP_NAME_SLUG}}

# 6. Mostrar status
echo "[6/6] Verificando que arrancó..."
sleep 2
sudo systemctl status {{APP_NAME_SLUG}} --no-pager || true

echo ""
echo "=========================================="
echo "  ✅ {{APP_NAME}} instalado!"
echo "=========================================="
echo "  Corriendo en: http://$(curl -s ifconfig.me):8001"
echo ""
echo "  PRÓXIMO PASO: configurar HTTPS con Nginx + Let's Encrypt:"
echo "    sudo nano /etc/nginx/sites-available/{{APP_NAME_SLUG}}"
echo "    sudo certbot --nginx -d TU_DOMINIO.com"
echo ""
echo "  Logs en vivo:"
echo "    sudo journalctl -u {{APP_NAME_SLUG}} -f"
echo "=========================================="
