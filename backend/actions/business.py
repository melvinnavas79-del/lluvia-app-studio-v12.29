"""
========================================
ACCIONES DE NEGOCIO / RESPUESTAS
========================================
"""

import config


def auto_reply() -> str:
    return (
        "Hola, soy el Asistente Oficial de Lluvia App Studio. "
        "Cuentame que necesitas: una app, un repositorio, automatizar tu negocio "
        "o publicar en redes sociales."
    )


def greeting() -> str:
    return (
        "Hola, soy el Asistente Oficial de Lluvia App Studio.\n\n"
        "Tengo acceso tecnico para crear apps y landings, gestionar tu GitHub "
        "y ejecutar comandos en el servidor cuando el admin lo ordene.\n\n"
        "Comandos rapidos:\n"
        "  /help              ver todos los comandos\n"
        "  /mi-rendimiento    si eres afiliado, ver tus ventas\n"
        "  crear app <nombre> generar una landing\n\n"
        "Tambien puedes preguntarme cualquier cosa de negocio y te respondo con IA."
    )


def help_text() -> str:
    return (
        "Comandos disponibles:\n"
        "- /mi-rendimiento        -> tus ventas y comisiones (afiliados)\n"
        "- crear app <nombre>     -> genera una landing/web (admin)\n"
        "- crear repo <nombre>    -> crea repositorio en GitHub (admin)\n"
        "- listar repos           -> lista tus repos (admin)\n"
        "- ejecuta <comando>      -> ejecuta comando shell (admin only)\n"
        "- /status                -> estado del bot\n"
        "- (cualquier otra cosa)  -> conversa con la IA"
    )


def status_text() -> str:
    s = config.credentials_status()
    def yn(v: bool) -> str:
        return "OK" if v else "NO"
    return (
        "Estado del Bot Multiplataforma:\n"
        f"- GitHub:    {yn(s['github'])}\n"
        f"- WhatsApp:  {yn(s['whatsapp'])}\n"
        f"- Telegram:  {yn(s['telegram'])}\n"
        f"- Instagram: {yn(s['instagram'])}\n"
        f"- IA lista:  {yn(s['llm_ready'])} (modelo {s.get('model', '?')})\n"
    )


def social_post(text: str) -> str:
    return (
        "Funcion de publicacion en redes sociales en preparacion. "
        "Configura tus tokens de Meta/Twitter para activarla."
    )
