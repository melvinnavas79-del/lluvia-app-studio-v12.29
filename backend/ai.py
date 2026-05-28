"""
========================================
MOTOR DE IA (GPT) - AGENTE OPERARIO
========================================

Sin ego, sin clases, sin planes. Ejecuta tools y reporta.
"""

import json
import logging

import config
import llm_router
import memory
from actions import github as gh
from actions import server as srv
from actions import client_provisioning
from security import is_command_safe

logger = logging.getLogger(__name__)


SYSTEM_MESSAGE_BASE = (
    "ROL: Operario de Lluvia App Studio. Ejecutas, no enseñas.\n"
    "\n"
    "REGLAS DURAS (jamas las rompas):\n"
    "1. PROHIBIDO: planes numerados, listas '### Pasos a seguir', '¿Como proceder?', "
    "explicar que es backend/frontend/streaming/donaciones, preguntar lenguaje/framework/"
    "software/sistema de pago, ofrecer 'alternativas', frases tipo 'puedo proceder a...'.\n"
    "2. STACK FIJO: Lluvia App Studio (FastAPI + React + Mongo + Docker + Caddy + OpenAI). "
    "NUNCA preguntes preferencias tecnicas. Asumelo siempre.\n"
    "3. Toda orden razonable -> llamas la tool correspondiente y reportas resultado en MAXIMO 3 LINEAS.\n"
    "4. Si la tool devuelve error -> repites el error textual, no inventas solucion ni das clases.\n"
    "5. Si te falta UN dato esencial (ej. nombre del cliente) -> UNA pregunta de UNA linea. "
    "Nada mas. No expliques por que la pides.\n"
    "6. Cero markdown decorativo: sin '###', sin '**', sin emojis (salvo ✅ o ❌ al reportar).\n"
    "7. No saludes, no te despidas, no resumas, no expliques, no recomiendes. "
    "Solo: ejecutar -> reportar.\n"
    "8. NUNCA inventes contenido de archivos, ni de comandos, ni de repos. Si no llamaste la tool, "
    "no tienes el dato. Llama la tool.\n"
    "\n"
    "TOOLS DISPONIBLES (uso obligatorio segun caso):\n"
    "- 'instalar/crear/desplegar radio/app/tienda/blog/web para X' -> provision_client_quick(display_name=X)\n"
    "- 'cuanta RAM/disco/uptime/CPU' -> shell_run\n"
    "- 'lista mis repos / cuantos repos tengo' -> github_list_repos\n"
    "- 'que hay en repo X / lee README de X / busca audio en X' -> github_list_files / github_read_file / github_search_code\n"
    "\n"
    "EJEMPLOS DE BUEN COMPORTAMIENTO:\n"
    "Usuario: 'instala una radio para Pedro Martinez'\n"
    "Tu: [tool: provision_client_quick(display_name='Pedro Martinez')]\n"
    "Tu (tras tool): '✅ Listo. https://pedro-martinez.lluvia.app | admin: admin@pedro-martinez.lluvia.app | pass: Xy7abc...'\n"
    "\n"
    "Usuario: 'dame la RAM'\n"
    "Tu: [tool: shell_run(command='free -h')]\n"
    "Tu (tras tool): 'RAM: 7.7Gi total, 5.2Gi libres.'\n"
    "\n"
    "EJEMPLOS DE COMPORTAMIENTO PROHIBIDO (jamas hagas esto):\n"
    "❌ '### Pasos a seguir: 1. Elegir software de streaming 2. Desarrollar backend...'\n"
    "❌ 'Si tienes preferencias sobre lenguaje de programacion, hazmelo saber.'\n"
    "❌ 'Alternativamente, puedo proceder a instalar un software predeterminado. ¿Que prefieres?'\n"
    "❌ Cualquier respuesta sin tool call cuando la orden requiere accion.\n"
)

ADMIN_HINT = (
    "\nEste chat YA esta vinculado como ADMIN. Acceso total a tools. Ejecuta sin pedir permiso."
)
NON_ADMIN_HINT = (
    "\nEste chat NO es admin. No tienes tools. Si te piden accion, responde en UNA linea: "
    "'Vinculate primero: /vincular-admin <password>'."
)


# ============================================================
# DEFINICION DE TOOLS PARA OPENAI
# ============================================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "provision_client_quick",
            "description": (
                "Despliega un cliente NUEVO end-to-end con el stack Lluvia (FastAPI+React+Mongo+Docker+Caddy). "
                "USAR cuando el admin diga 'instala/crea/despliega/monta una radio/app/tienda/blog/web/sistema/landing/CRM/bot para <Nombre>'. "
                "Asume defaults Lluvia (colores, sin logo, email autogenerado si no se da). "
                "Devuelve URL publica + credenciales del admin del cliente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "display_name": {
                        "type": "string",
                        "description": "Nombre del cliente o del producto (ej: 'Pedro Martinez', 'Radio Acme')",
                    },
                    "admin_email": {
                        "type": "string",
                        "description": "Email admin del cliente. Opcional. Si vacio, se autogenera.",
                    },
                    "app_type": {
                        "type": "string",
                        "description": "Tipo de app: radio, tienda, blog, landing, crm, etc. Solo informativo.",
                    },
                },
                "required": ["display_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_repos",
            "description": "Lista los repositorios del usuario en GitHub.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_list_files",
            "description": "Lista archivos y carpetas dentro de un repo en una ruta. Vacio = raiz.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "path": {"type": "string", "default": ""},
                },
                "required": ["repo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_read_file",
            "description": "Lee el contenido de un archivo de texto en un repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "file_path": {"type": "string"},
                },
                "required": ["repo", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github_search_code",
            "description": "Busca un texto/codigo dentro de un repo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["repo", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_run",
            "description": "Ejecuta un comando shell SEGURO en el servidor (con safety). Para RAM, disco, uptime, ps, df, free, uname.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
]


async def _execute_tool(name: str, args: dict, is_admin: bool) -> str:
    """Ejecuta una tool y devuelve el resultado serializado en JSON."""
    try:
        if name == "github_list_repos":
            data = gh.tool_list_repos_short()
        elif name == "github_list_files":
            data = gh.tool_list_files(args.get("repo", ""), args.get("path", ""))
        elif name == "github_read_file":
            data = gh.tool_read_file(args.get("repo", ""), args.get("file_path", ""))
        elif name == "github_search_code":
            data = gh.tool_search_code(args.get("repo", ""), args.get("query", ""))
        elif name == "shell_run":
            if not is_admin:
                return json.dumps({"error": "Esta tool requiere admin vinculado"})
            cmd = args.get("command", "")
            safe, reason = is_command_safe(cmd)
            if not safe:
                return json.dumps({"error": f"Comando bloqueado: {reason}"})
            data = {"command": cmd, "output": srv.run_command(cmd)}
        elif name == "provision_client_quick":
            if not is_admin:
                return json.dumps({"error": "Esta tool requiere admin vinculado"})
            output = await client_provisioning.quick_provision(
                display_name=args.get("display_name", ""),
                admin_email=args.get("admin_email", ""),
                app_type=args.get("app_type", "default"),
            )
            data = {"result": output}
        else:
            data = {"error": f"Tool desconocida: {name}"}
        return json.dumps(data, ensure_ascii=False)[:30000]
    except Exception as e:
        return json.dumps({"error": str(e)})


def is_ready() -> bool:
    return llm_router.llm_available()


def _build_messages(user: str, text: str, is_admin: bool) -> list:
    history = memory.get(user)
    system = SYSTEM_MESSAGE_BASE + (ADMIN_HINT if is_admin else NON_ADMIN_HINT)
    messages = [{"role": "system", "content": system}]
    for entry in history[-(memory.MAX_HISTORY * 2):]:
        role = entry.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": entry.get("content", "")})
    messages.append({"role": "user", "content": text})
    return messages


async def generate(user: str, text: str, is_admin: bool = False) -> str:
    if not llm_router.llm_available():
        return "Motor IA no configurado. Agrega GROQ_API_KEY o OPENAI_API_KEY en backend/.env"

    try:
        client, llm_model = llm_router.get_client("low")
        messages = _build_messages(user, text, is_admin)

        # Loop de tool calling: hasta 5 vueltas
        for _ in range(5):
            response = await client.chat.completions.create(
                model=llm_model,
                messages=messages,
                tools=TOOLS if is_admin else None,
                tool_choice="auto" if is_admin else None,
                temperature=0.2,
                max_tokens=400,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                # Respuesta final
                reply = msg.content or ""
                memory.save(user, "user", text)
                memory.save(user, "assistant", reply)
                return reply

            # El modelo pidio tool calls -> ejecutarlas
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                logger.info(f"[ai] tool_call: {tc.function.name}({args})")
                result = await _execute_tool(tc.function.name, args, is_admin)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return "Lo siento, mi razonamiento se quedo dando vueltas. Intenta reformular la pregunta."

    except Exception as e:
        logger.error(f"Error generando respuesta IA: {e}")
        return f"Error generando respuesta: {str(e)}"
