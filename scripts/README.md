# 🚀 Lluvia App Studio — Pipeline de "1 cliente por hora"

Sistema de despliegue automatizado de copias del bot. Cada cliente queda **totalmente aislado** (su propia base de datos, su propio dominio, su propio branding).

---

## 📦 Lo que incluye este paquete

| Archivo | Para qué sirve |
|---|---|
| `infra-init.sh` | **Una sola vez** en el VPS: levanta Caddy (reverse-proxy global con SSL automático) |
| `setup-cliente.sh` | **Cada cliente nuevo**: pregunta datos, genera todo, despliega en ~5-10 min |
| `templates/` | Dockerfiles, docker-compose y Caddyfile que el script usa para generar cada cliente |

---

## ✅ Guía rápida de 5 pasos

### 1. Pre-requisitos (una sola vez)
- VPS con **Linux** (Ubuntu 22.04+ recomendado)
- **Docker** y **Docker Compose v2** instalados
- Un **dominio** (ej: `lluvia.app`) con **DNS wildcard** apuntando al VPS:
  ```
  *.lluvia.app    A    <IP_DEL_VPS>
  ```
- El código fuente del bot copiado en `/opt/lluvia/source/` (carpetas `backend/` y `frontend/`)

### 2. Levantar la infraestructura global (una sola vez)
```bash
export LLUVIA_ADMIN_EMAIL="melvinnavas79@gmail.com"
export LLUVIA_ROOT_DOMAIN="lluvia.app"
sudo bash /opt/lluvia/scripts/infra-init.sh
```
Esto deja Caddy corriendo en :80/:443 con SSL automático.

### 3. (Opcional) Setear tu OpenAI key como default para todos los clientes
```bash
export LLUVIA_DEFAULT_OPENAI="sk-proj-tu-key-master"
```
Cuando ejecutes `setup-cliente.sh` te dejará entrar con ENTER y usará esta key. Si el cliente luego quiere usar la suya, solo edita `backend.env` y reinicia.

### 4. Desplegar un cliente nuevo
```bash
sudo -E bash /opt/lluvia/scripts/setup-cliente.sh
```
El script te pregunta interactivamente:
- Nombre del cliente (ej: `Acme Corp`) → genera slug `acme-corp` automáticamente
- Dominio raíz (default: `lluvia.app`) → URL final = `https://acme-corp.lluvia.app`
- Producto / tagline / **logo URL** / **4 colores hex** / email admin / password
- OpenAI key del cliente (vacío = usa tu master)
- Telegram token del cliente (opcional, configurable después)

Y hace todo automáticamente:
- ✅ Crea `/opt/lluvia/clients/<slug>/` con código fuente aislado
- ✅ MongoDB privado por cliente (volumen `lluvia_<slug>_mongo_data`)
- ✅ Backend + Frontend en Docker, redes separadas
- ✅ Caddyfile del cliente + reload de Caddy → HTTPS automático
- ✅ Login admin + PUT /api/branding con su logo y colores
- ✅ Te imprime URL final + credenciales

### 5. Entregar al cliente
El script te muestra al final:
```
URL Panel:    https://acme-corp.lluvia.app
Admin Email:  cliente@acme.com
Admin Pass:   xK9fL2mP3qWz
```
Le mandas eso por email/WhatsApp y listo.

---

## 🛠️ Mantenimiento por cliente

```bash
cd /opt/lluvia/clients/<slug>

docker compose logs -f          # ver logs
docker compose restart backend  # reiniciar solo backend
docker compose down             # detener (los datos persisten)
docker compose down -v          # detener y BORRAR la DB (cuidado!)
docker compose pull && docker compose up -d --build  # actualizar
```

---

## 🔐 Aislamiento total garantizado

| Recurso | Aislamiento |
|---|---|
| Base de datos | Volumen Docker exclusivo `lluvia_<slug>_mongo_data` |
| Backend | Container con `backend.env` único (JWT secret diferente por cliente) |
| Frontend | Build separado con su `REACT_APP_BACKEND_URL` propio |
| Red interna | Network Docker `lluvia_<slug>_internal` solo para ese cliente |
| Branding | Documento singleton en su MongoDB privado |
| Telegram bot | Token único por cliente (cada uno usa su `@BotFather`) |
| OpenAI | Cada cliente puede tener su propia key |
| Dominio | Subdominio dedicado con SSL propio |

---

## 📈 Tiempos reales

| Paso | Tiempo |
|---|---|
| Pre-requisitos (DNS + VPS + Docker) | 15 min, una sola vez |
| `infra-init.sh` (Caddy) | 1 min, una sola vez |
| **Cada cliente nuevo (`setup-cliente.sh`)** | **~5-10 min** |

→ Pipeline objetivo de **"1 cliente por hora" cumplido con margen** (te alcanza para ~6 clientes/hora).

---

## ⚠️ Antes de salir a vender

1. **Rotar todas las credenciales que compartiste en chat** (TELEGRAM_TOKEN, GITHUB_TOKEN, OPENAI_API_KEY, JWT_SECRET).
2. **Comprar el dominio raíz** (`lluvia.app` u otro) y configurar DNS wildcard.
3. **Probar el pipeline con 1 cliente de prueba** antes del primero real.
4. **Backups periódicos** de los volúmenes Mongo (`docker run --rm -v lluvia_<slug>_mongo_data:/data alpine tar czf - /data`).

---

## 🆘 Troubleshooting

- **"PUT branding falló" al final del script**: el DNS aún no propaga. Espera 1-2 min y aplica branding manualmente desde el panel del cliente.
- **"Caddy no recargó"**: ejecuta `docker exec lluvia_caddy caddy reload --config /etc/caddy/Caddyfile` manualmente.
- **Backend no arranca**: `cd /opt/lluvia/clients/<slug> && docker compose logs backend`.

---

**Lluvia App Studio** · pipeline de despliegue v1.0 · enero 2026
