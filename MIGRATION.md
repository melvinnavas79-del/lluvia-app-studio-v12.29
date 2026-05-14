# Lluvia App Studio — Guia de Migracion a VPS (v10)

Esta guia te lleva del paquete `lluvia-deploy.tar.gz` a un VPS de
produccion con HTTPS automatico, Mongo persistente y multi-cliente.

## 1. Requisitos del VPS

- Ubuntu 22.04 / 24.04 LTS (o Debian 12 Bookworm)
- 8 GB RAM minimo (recomendado para 3-5 clientes simultaneos)
- 50 GB SSD
- Dominio apuntando al VPS con wildcard (`*.lluvia.app`)
- Acceso root via SSH

## 2. Pre-requisitos del sistema

```bash
# Docker + Compose v2
curl -fsSL https://get.docker.com | sh
sudo apt-get install -y docker-compose-plugin

# Caddy (reverse proxy con HTTPS automatico)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## 3. Descomprimir el paquete

```bash
sudo mkdir -p /opt/lluvia
sudo tar -xzf lluvia-deploy.tar.gz -C /opt/lluvia
cd /opt/lluvia
ls   # scripts/  source/  README.md
```

## 4. Configurar variables maestras

Edita `/opt/lluvia/source/backend/.env`:

```env
MONGO_URL=mongodb://mongo:27017
DB_NAME=lluvia_admin

# Secretos (ROTAR todos antes de produccion)
JWT_SECRET=<genera con: openssl rand -hex 32>
ADMIN_EMAIL=tu_email@dominio.com
ADMIN_PASSWORD=<password fuerte>

# APIs
OPENAI_API_KEY=sk-...
TELEGRAM_TOKEN=<de @BotFather>
GITHUB_TOKEN=<personal access token>

# PayPal (live)
PAYPAL_MODE=live
PAYPAL_CLIENT_ID=...
PAYPAL_SECRET=...
PAYPAL_WEBHOOK_ID=...   # obligatorio para que el webhook valide firma

# Lluvia infra
LLUVIA_HOME=/opt/lluvia
LLUVIA_BASE_DOMAIN=lluvia.app
LLUVIA_DRY_RUN=0
TELEGRAM_POLLING=1
LLM_MODEL=gpt-4o-mini
```

## 5. Inicializar Caddy global

```bash
cd /opt/lluvia/scripts
sudo ./infra-init.sh
```

Esto crea `/etc/caddy/Caddyfile.d/lluvia-global.conf` con reverse proxy
para cada cliente (`*.lluvia.app -> docker container`) y SSL automatico.

## 6. Levantar el panel maestro

```bash
cd /opt/lluvia/source
sudo docker compose up -d
sudo docker compose logs -f backend
```

Verifica: `https://admin.lluvia.app` carga el panel y permite login.

## 7. Crear primer cliente

Desde tu Telegram (vinculado como admin):

```
/vincular-admin <tu password>
/cliente nuevo
```

O via el agente DevOps en el panel:
> "instala una radio para Acme Corp"

El script `setup-cliente.sh` provisiona un container con Mongo aislado,
Caddyfile dedicado, branding por defecto y devuelve URL + credenciales.

## 8. Configurar PayPal webhook

En el dashboard de PayPal:

1. Apps & Credentials -> Webhooks -> Add Webhook
2. URL: `https://admin.lluvia.app/api/paypal/webhook`
3. Eventos: `PAYMENT.CAPTURE.COMPLETED`
4. Copia el Webhook ID -> pegalo en `PAYPAL_WEBHOOK_ID` del `.env`
5. Reinicia: `docker compose restart backend`

Sin `PAYPAL_WEBHOOK_ID`, el endpoint `/api/paypal/webhook` **rechaza
todas las llamadas con 403**. Es una proteccion de seguridad: nadie
puede acreditarse oros sin que PayPal lo confirme con firma.

## 9. Backups automaticos

Cron diario para Mongo de cada cliente:

```bash
sudo crontab -e
# Agregar:
0 3 * * * /opt/lluvia/scripts/backup-clients.sh >> /var/log/lluvia-backup.log 2>&1
```

(El script `backup-clients.sh` esta en `scripts/` del paquete.)

## 10. Monitoreo basico

```bash
# Estado de todos los clientes
sudo docker ps --filter "name=lluvia-"

# Logs de un cliente puntual
sudo docker logs -f lluvia-acme-corp-backend

# Espacio
df -h /opt/lluvia
```

## 11. Actualizacion a v11+

```bash
cd /opt/lluvia
sudo tar -xzf lluvia-deploy-v11.tar.gz --strip-components=0
cd source
sudo docker compose up -d --build
```

El sistema de Propuestas conserva su historial entre versiones (Mongo).

---

## Checklist final pre-venta

- [ ] Dominio + wildcard DNS apuntando al VPS
- [ ] `.env` con secretos rotados (NO usar los del repo)
- [ ] `ADMIN_PASSWORD` cambiado del default
- [ ] `PAYPAL_WEBHOOK_ID` configurado
- [ ] PayPal en modo `live` (no sandbox)
- [ ] `infra-init.sh` ejecutado exitosamente
- [ ] Login en `admin.<dominio>` funcionando
- [ ] Primer cliente desplegado y accesible
- [ ] Backup nocturno verificado (cron + restore test)
- [ ] Telegram bot respondiendo a `/start`

— Lluvia App Studio v10
