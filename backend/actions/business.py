"""
========================================
ACCIONES DE NEGOCIO / RESPUESTAS
========================================
"""

import config


def auto_reply() -> str:
    return (
        "Gracias por contactarnos. Estoy aqui para ayudarte. "
        "Cuentame que necesitas: una app, un repositorio, automatizar tu negocio "
        "o publicar en redes sociales."
    )


def help_text() -> str:
    return (
        "Comandos disponibles:\n"
        "- /mi-rendimiento        -> tus ventas y comisiones (afiliados)\n"
        "- crear app <nombre>     -> genera una landing/web\n"
        "- crear repo <nombre>    -> crea un repositorio en GitHub\n"
        "- listar repos           -> lista tus repos\n"
        "- ejecuta <comando>      -> ejecuta un comando shell seguro\n"
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
        f"- IA lista:  {yn(s['llm_ready'])} (modelo {s['model']} via {s['provider']})\n"
    )


def social_post(text: str) -> str:
    return (
        "Funcion de publicacion en redes sociales en preparacion. "
        "Configura tus tokens de Meta/Twitter para activarla."
    )
