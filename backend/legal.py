"""
============================================================
DOCUMENTOS LEGALES — Términos / Privacidad / Cookies
============================================================
Plantillas razonables en español neutro, listas para uso público.
IMPORTANTE: Antes de cobrar a clientes reales, recomendamos
que un abogado de tu jurisdicción los revise para cumplir con
GDPR (Europa), LFPDPPP (México), LGPD (Brasil), etc.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime, timezone

router = APIRouter(prefix="/legal", tags=["legal"])


COMPANY_NAME = "Lluvia App Studio"
COMPANY_EMAIL = "melvinnavas79@gmail.com"
COMPANY_DOMAIN = "lluvia-app-studio.lluvia-live.com"
LAST_UPDATE = "16 de mayo de 2026"


_BASE_CSS = """
<style>
  body { font-family: 'Inter', system-ui, sans-serif; max-width: 820px;
         margin: 2rem auto; padding: 0 1.5rem; line-height: 1.7;
         color: #111827; background: #FDFBF7; }
  h1 { font-size: 2.2rem; letter-spacing: -0.025em; margin-bottom: 0.3rem; }
  h2 { margin-top: 2.2rem; font-size: 1.4rem; letter-spacing: -0.02em;
       color: #0F172A; border-bottom: 1px solid #E7E5E0; padding-bottom: 0.4rem; }
  h3 { margin-top: 1.4rem; font-size: 1.1rem; color: #1F2937; }
  .meta { color: #6B7280; font-size: 0.9rem; margin-bottom: 2rem; }
  a { color: #2563EB; }
  ul li { margin: 0.4rem 0; }
  .nav { background: #fff; border: 1px solid #E7E5E0; padding: 1rem;
         border-radius: 12px; display: flex; gap: 1rem; flex-wrap: wrap;
         margin-bottom: 2rem; }
  .nav a { text-decoration: none; font-weight: 500; color: #0F172A; }
  .nav a:hover { color: #2563EB; }
  footer { margin: 3rem 0 1rem; color: #6B7280; font-size: 0.85rem;
           text-align: center; border-top: 1px solid #E7E5E0; padding-top: 1rem; }
</style>
"""

_NAV = f"""
<nav class="nav">
  <a href="/api/legal/terms">Términos de Servicio</a>
  <a href="/api/legal/privacy">Política de Privacidad</a>
  <a href="/api/legal/cookies">Política de Cookies</a>
  <a href="https://{COMPANY_DOMAIN}">← Volver a la app</a>
</nav>
"""

_FOOTER = f"""
<footer>
  &copy; {datetime.now(timezone.utc).year} {COMPANY_NAME}.<br>
  Contacto: <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a>
</footer>
"""


# ============================================================
# TÉRMINOS DE SERVICIO
# ============================================================
@router.get("/terms", response_class=HTMLResponse)
async def terms_of_service():
    return f"""<!doctype html>
<html lang="es"><head>
  <meta charset="utf-8">
  <title>Términos de Servicio · {COMPANY_NAME}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_BASE_CSS}
</head><body>
  {_NAV}
  <h1>Términos de Servicio</h1>
  <p class="meta">Última actualización: {LAST_UPDATE}</p>

  <p>Bienvenido a <strong>{COMPANY_NAME}</strong> (en adelante, "la Plataforma",
  "nosotros" o "el Servicio"), disponible en
  <a href="https://{COMPANY_DOMAIN}">{COMPANY_DOMAIN}</a>. Estos Términos de
  Servicio regulan el uso de la Plataforma. Al registrarte o utilizar el Servicio
  aceptas cumplir con estos Términos. Si no estás de acuerdo, no uses la Plataforma.</p>

  <h2>1. Descripción del Servicio</h2>
  <p>{COMPANY_NAME} ofrece una plataforma de software como servicio (SaaS) que
  permite a los usuarios crear, desplegar y administrar agentes de inteligencia
  artificial conversacionales, además de construir aplicaciones web multimedia
  con apoyo de IA. El servicio incluye:</p>
  <ul>
    <li>Chat con agentes IA especializados (consume créditos llamados "oros").</li>
    <li>Generación de código y despliegue de aplicaciones a tu propio repositorio de GitHub.</li>
    <li>Integraciones con servicios de terceros (OpenAI, PayPal, Telegram).</li>
    <li>Panel de administración white-label para personalizar la apariencia.</li>
  </ul>

  <h2>2. Cuenta y Registro</h2>
  <p>Para usar el Servicio debés crear una cuenta proporcionando un email válido
  y una contraseña. Sos responsable de mantener la confidencialidad de tus
  credenciales. Las cuentas son personales e intransferibles. Al registrarte
  recibís un saldo inicial de cortesía de <strong>15 oros</strong>.</p>

  <h2>3. Créditos ("oros") y Pagos</h2>
  <p>El Servicio opera con un sistema de créditos llamados "oros". Cada acción
  realizada (mensaje, llamada a voz, push a GitHub, etc.) descuenta una cantidad
  específica del saldo del usuario. Los oros se compran en paquetes pagados
  con PayPal a través del proveedor de pagos integrado.</p>
  <ul>
    <li>Los pagos son procesados por PayPal Inc. Aplican sus propios términos.</li>
    <li>Los oros <strong>no son reembolsables</strong> una vez acreditados, salvo en
        casos de error técnico verificable atribuible a la Plataforma.</li>
    <li>Los oros no expiran mientras la cuenta permanezca activa.</li>
    <li>Los oros no tienen valor monetario fuera del Servicio y no son canjeables
        por dinero ni transferibles entre cuentas.</li>
  </ul>

  <h2>4. Uso Aceptable</h2>
  <p>Al usar el Servicio, te comprometés a NO:</p>
  <ul>
    <li>Generar contenido ilegal, violento, sexual con menores, discriminatorio,
        de odio, fraudulento o que infrinja derechos de terceros.</li>
    <li>Usar la Plataforma para enviar spam, phishing o malware.</li>
    <li>Intentar acceder sin autorización a cuentas, sistemas o datos ajenos.</li>
    <li>Realizar ingeniería inversa, descompilar o explotar vulnerabilidades del
        Servicio.</li>
    <li>Revender el acceso a la Plataforma sin autorización escrita previa.</li>
    <li>Usar la Plataforma para automatizar interacciones engañosas o suplantar
        identidad.</li>
  </ul>
  <p>Nos reservamos el derecho de suspender o cancelar cuentas que violen estas
  reglas, sin reembolso de oros adquiridos.</p>

  <h2>5. Propiedad Intelectual</h2>
  <p>El código fuente de la Plataforma, su diseño, marca, logos y documentación
  son propiedad de {COMPANY_NAME}. El <strong>contenido y código generado por
  vos usando la Plataforma es de tu propiedad</strong>, y podés empujarlo a tu
  propio repositorio de GitHub usando la función Push integrada. La Plataforma
  conserva el derecho de usar metadatos anónimos sobre el uso para mejorar
  el Servicio.</p>

  <h2>6. Integraciones de Terceros</h2>
  <p>La Plataforma usa servicios de terceros (OpenAI, PayPal, Telegram, GitHub).
  Su disponibilidad y términos no dependen de nosotros. Si un servicio de tercero
  se interrumpe, la funcionalidad relacionada de la Plataforma puede verse
  afectada temporalmente.</p>

  <h2>7. Limitación de Responsabilidad</h2>
  <p>El Servicio se ofrece "tal como está". En la máxima medida permitida por
  la ley aplicable, <strong>{COMPANY_NAME} NO será responsable</strong> por:</p>
  <ul>
    <li>Pérdida de datos o de oros derivada de fallos técnicos de terceros.</li>
    <li>Daños indirectos, lucro cesante o perjuicios consecuenciales.</li>
    <li>Mal uso del Servicio por parte del usuario o de terceros.</li>
    <li>Contenido generado por la IA que pueda contener errores, sesgos o
        información inexacta. La IA es una herramienta auxiliar, no un sustituto
        de asesoramiento profesional (médico, legal, financiero, etc.).</li>
  </ul>
  <p>La responsabilidad total de la Plataforma, en cualquier caso, se limita al
  monto pagado por el usuario durante los 30 días anteriores al hecho que
  origine la reclamación.</p>

  <h2>8. Modificaciones al Servicio</h2>
  <p>Podemos modificar, suspender o discontinuar el Servicio (o partes de él)
  en cualquier momento, con o sin previo aviso. Si una modificación afecta
  materialmente derechos adquiridos (oros comprados), te notificaremos por email
  con al menos 30 días de anticipación.</p>

  <h2>9. Cancelación</h2>
  <p>Podés cancelar tu cuenta en cualquier momento desde el panel "Mi Cuenta"
  o escribiéndonos a <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a>. Al
  cancelar, tu acceso al Servicio termina inmediatamente. Los oros no usados
  no son reembolsables.</p>

  <h2>10. Ley Aplicable y Jurisdicción</h2>
  <p>Estos Términos se rigen por las leyes del país de domicilio de
  {COMPANY_NAME}. Cualquier disputa se resolverá en los tribunales competentes
  de dicha jurisdicción. Si una cláusula es declarada inválida, el resto de los
  Términos continúa vigente.</p>

  <h2>11. Contacto</h2>
  <p>Si tenés preguntas o reclamos sobre estos Términos, escribinos a
  <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a>.</p>

  {_FOOTER}
</body></html>"""


# ============================================================
# POLÍTICA DE PRIVACIDAD
# ============================================================
@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return f"""<!doctype html>
<html lang="es"><head>
  <meta charset="utf-8">
  <title>Política de Privacidad · {COMPANY_NAME}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_BASE_CSS}
</head><body>
  {_NAV}
  <h1>Política de Privacidad</h1>
  <p class="meta">Última actualización: {LAST_UPDATE}</p>

  <p>En <strong>{COMPANY_NAME}</strong> respetamos tu privacidad. Esta política
  describe qué datos recolectamos, para qué los usamos y cuáles son tus derechos.</p>

  <h2>1. Datos que Recolectamos</h2>
  <h3>1.1 Datos que vos nos proporcionás</h3>
  <ul>
    <li><strong>Cuenta</strong>: email, contraseña (hasheada con bcrypt), nombre opcional.</li>
    <li><strong>Pagos</strong>: PayPal nos comparte un identificador de orden y el
        monto. <em>Nunca</em> almacenamos números de tarjeta ni credenciales de PayPal.</li>
    <li><strong>Tokens de integración</strong>: si configurás tu GITHUB_TOKEN, este
        se guarda cifrado en nuestra base de datos. Solo se usa para hacer push
        a tu repositorio cuando vos lo solicitás.</li>
    <li><strong>Mensajes de chat</strong>: el contenido de tus conversaciones con
        los agentes IA se guarda en tu sesión para que puedas continuar
        conversaciones. Estos mensajes se envían a OpenAI para generar las
        respuestas (ver sección 3).</li>
  </ul>

  <h3>1.2 Datos que se generan automáticamente</h3>
  <ul>
    <li>Dirección IP, navegador, sistema operativo.</li>
    <li>Logs técnicos de errores y métricas de uso (volumen de mensajes, llamadas
        a tools, etc.). Estos datos están seudonimizados.</li>
    <li>Cookies de sesión (ver Política de Cookies).</li>
  </ul>

  <h2>2. Para Qué Usamos Tus Datos</h2>
  <ul>
    <li>Proveer el Servicio y mantener tu sesión activa.</li>
    <li>Procesar pagos a través de PayPal y acreditar oros.</li>
    <li>Permitirte usar las funciones de chat, push a GitHub, etc.</li>
    <li>Mejorar el Servicio analizando métricas agregadas y anónimas.</li>
    <li>Enviarte comunicaciones operativas (recibos, notificaciones de seguridad).
        Solo enviamos publicidad si activamente lo aceptás.</li>
    <li>Cumplir obligaciones legales (fiscales, contables).</li>
  </ul>

  <h2>3. Compartición con Terceros</h2>
  <p>Compartimos datos estrictamente con los siguientes proveedores, solo cuando
  es necesario para ejecutar el Servicio:</p>
  <ul>
    <li><strong>OpenAI</strong> (USA) — para generar respuestas de los agentes IA.
        Sujeto a la política de OpenAI: <a href="https://openai.com/privacy">openai.com/privacy</a></li>
    <li><strong>PayPal Inc.</strong> (USA) — para procesar pagos.</li>
    <li><strong>Telegram</strong> (UK) — si activás la integración del bot.</li>
    <li><strong>GitHub Inc.</strong> (USA) — si activás push, tu código se envía a
        tu propio repositorio.</li>
    <li><strong>Proveedor de hosting</strong> — la infraestructura corre sobre un
        proveedor cloud profesional con cifrado en tránsito y en reposo.</li>
  </ul>
  <p><strong>Nunca vendemos tus datos.</strong> Solo los compartimos con autoridades
  bajo requerimiento legal vinculante.</p>

  <h2>4. Retención</h2>
  <ul>
    <li>Datos de cuenta: mientras tu cuenta esté activa, más 90 días tras la
        cancelación (para auditoría fiscal y resolver disputas).</li>
    <li>Mensajes de chat: mientras tu cuenta esté activa. Podés borrar sesiones
        individuales desde el panel.</li>
    <li>Datos de pago: 7 años (obligación fiscal en la mayoría de jurisdicciones).</li>
    <li>Logs técnicos: 90 días.</li>
  </ul>

  <h2>5. Tus Derechos</h2>
  <p>Tenés derecho a:</p>
  <ul>
    <li><strong>Acceder</strong> a los datos personales que tenemos sobre vos.</li>
    <li><strong>Rectificar</strong> datos inexactos.</li>
    <li><strong>Suprimir</strong> tus datos (derecho al olvido), salvo aquellos que
        estamos obligados a conservar por ley.</li>
    <li><strong>Exportar</strong> tus datos en formato legible (portabilidad).</li>
    <li><strong>Oponerte</strong> al tratamiento automatizado.</li>
    <li><strong>Retirar tu consentimiento</strong> para usos secundarios (marketing).</li>
  </ul>
  <p>Para ejercerlos, escribinos a <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a>.
  Respondemos en máximo 30 días.</p>

  <h2>6. Seguridad</h2>
  <p>Aplicamos medidas técnicas y organizativas razonables: cifrado HTTPS en todas
  las conexiones, contraseñas hasheadas con bcrypt, tokens de API guardados
  cifrados, control de acceso por roles, y revisiones periódicas. Sin embargo,
  ningún sistema es 100% inviolable. Si detectamos una brecha de seguridad que
  afecte tus datos, te notificaremos en menos de 72 horas.</p>

  <h2>7. Menores</h2>
  <p>El Servicio no está dirigido a personas menores de 16 años. Si descubrimos
  que un menor creó una cuenta, la cerraremos.</p>

  <h2>8. Cambios a esta Política</h2>
  <p>Si hacemos cambios materiales, te notificaremos por email con 30 días de
  anticipación. La versión actual siempre está en esta URL.</p>

  <h2>9. Contacto del Responsable de Datos</h2>
  <p>{COMPANY_NAME} · <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a></p>

  {_FOOTER}
</body></html>"""


# ============================================================
# POLÍTICA DE COOKIES
# ============================================================
@router.get("/cookies", response_class=HTMLResponse)
async def cookies_policy():
    return f"""<!doctype html>
<html lang="es"><head>
  <meta charset="utf-8">
  <title>Política de Cookies · {COMPANY_NAME}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_BASE_CSS}
</head><body>
  {_NAV}
  <h1>Política de Cookies</h1>
  <p class="meta">Última actualización: {LAST_UPDATE}</p>

  <p>Esta política explica qué cookies y tecnologías similares usa
  <strong>{COMPANY_NAME}</strong>, para qué sirven y cómo podés gestionarlas.</p>

  <h2>1. ¿Qué es una cookie?</h2>
  <p>Una cookie es un pequeño archivo de texto que se guarda en tu dispositivo
  cuando visitás un sitio web. Sirve para que el sitio te reconozca, recuerde
  tus preferencias y funcione mejor.</p>

  <h2>2. Cookies que usamos</h2>
  <h3>2.1 Cookies estrictamente necesarias</h3>
  <p>Sin estas, el Servicio no puede funcionar. <strong>No requieren tu
  consentimiento</strong>.</p>
  <ul>
    <li><code>lluvia_session</code> / <code>access_token</code>: mantienen tu sesión
        iniciada. Duración: 30 días.</li>
    <li><code>lluvia-theme</code>: recuerda si elegiste tema claro u oscuro.
        Almacenado en localStorage del navegador, no se envía al servidor.</li>
    <li>Cookies anti-CSRF que protegen formularios de envíos no autorizados.</li>
  </ul>

  <h3>2.2 Cookies de funcionalidad</h3>
  <ul>
    <li>Preferencias de marca/branding del white-label de tu cuenta.</li>
    <li>Idioma de interfaz (si lo seleccionás manualmente).</li>
  </ul>

  <h3>2.3 Cookies de analítica</h3>
  <p>Actualmente <strong>NO usamos</strong> Google Analytics, Meta Pixel ni servicios
  de tracking de terceros. Si lo activamos en el futuro, actualizaremos esta
  política y pediremos tu consentimiento previo mediante un banner.</p>

  <h3>2.4 Cookies de terceros</h3>
  <p>Cuando hacés un pago con PayPal o usás la app móvil de Telegram para
  comunicarte con un agente, esos servicios pueden establecer sus propias
  cookies. Esas cookies se rigen por las políticas de PayPal y Telegram, no
  por la nuestra.</p>

  <h2>3. Cómo gestionar cookies</h2>
  <p>Podés:</p>
  <ul>
    <li>Borrar las cookies y datos de sitio desde la configuración de tu
        navegador (Chrome, Firefox, Safari, Edge).</li>
    <li>Configurar tu navegador para que rechace cookies. Atención: si
        rechazás las estrictamente necesarias, no podrás iniciar sesión.</li>
    <li>Cerrar sesión desde el botón "Salir" del panel: limpia el token de
        autenticación de tu navegador.</li>
  </ul>

  <h2>4. Actualizaciones</h2>
  <p>Esta política puede actualizarse para reflejar cambios técnicos o
  regulatorios. La versión vigente es siempre la disponible en esta URL.</p>

  <h2>5. Contacto</h2>
  <p>Preguntas sobre cookies: <a href="mailto:{COMPANY_EMAIL}">{COMPANY_EMAIL}</a></p>

  {_FOOTER}
</body></html>"""


# Endpoint JSON con metadata legal (útil para frontend)
@router.get("/info")
async def legal_info():
    return JSONResponse({
        "company": COMPANY_NAME,
        "support_email": COMPANY_EMAIL,
        "domain": COMPANY_DOMAIN,
        "last_update": LAST_UPDATE,
        "links": {
            "terms": "/api/legal/terms",
            "privacy": "/api/legal/privacy",
            "cookies": "/api/legal/cookies",
        },
    })
