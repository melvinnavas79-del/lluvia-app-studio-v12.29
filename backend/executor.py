"""
========================================
EJECUTOR DE ACCIONES
========================================

Llama a los modulos de actions/ segun el intent.
"""

import logging
from actions import github as gh
from actions import server as srv
from actions import apps as ap
from actions import business as bz

logger = logging.getLogger(__name__)


def execute_action(intent: dict, user: str = "default") -> str:
    action = intent.get("action", "")

    try:
        if action == "greeting":
            return bz.greeting()

        if action == "create_app":
            return ap.create_app(intent.get("raw", ""))

        if action == "github_create":
            return gh.create_repo(intent.get("raw", ""))

        if action == "github_list":
            return gh.list_repos()

        if action == "install_radio":
            return srv.install_radio()

        if action == "server_cmd":
            return srv.run_command(intent.get("cmd", ""))

        if action == "social_post":
            return bz.social_post(intent.get("raw", ""))

        if action == "business_reply":
            return bz.auto_reply()

        if action == "help":
            return bz.help_text()

        if action == "status":
            return bz.status_text()

        return "No entendi el comando. Escribe /help para ver lo que puedo hacer."

    except Exception as e:
        logger.exception(f"Error ejecutando accion {action}")
        return f"Error ejecutando '{action}': {e}"
