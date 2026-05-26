"""
E6 — Legal / Policies / Contracts
Sub-orquestador especializado en generación de documentos legales, contratos,
compliance y GDPR. Usa Groq para generación de texto legal — eficiente en costo.
No toca el legal.py estático existente (que sirve páginas HTML fijas).
"""
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
import llm_router

logger = logging.getLogger("e6_legal")
router = APIRouter(prefix="/e6", tags=["E6-Legal"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Constantes ───────────────────────────────────────────────────────────────

DOC_TYPES = ["tos", "privacy_policy", "contract", "nda", "gdpr_policy",
             "refund_policy", "cookie_policy", "disclaimer"]

JURISDICTIONS = ["argentina", "mexico", "colombia", "usa", "spain", "eu", "generic"]

TEMPLATES = {
    "tos": (
        "Genera unos Términos de Servicio profesionales para la plataforma '{product}' "
        "de la empresa '{company}' (jurisdicción: {jurisdiction}). "
        "Incluye secciones: Aceptación, Uso del Servicio, Pagos, Propiedad Intelectual, "
        "Privacidad, Limitación de Responsabilidad, Terminación, Ley Aplicable. "
        "Tono: formal, claro, en español. Máximo 800 palabras."
    ),
    "privacy_policy": (
        "Genera una Política de Privacidad profesional para '{product}' de '{company}' "
        "(jurisdicción: {jurisdiction}). Datos que se recopilan: {data_collected}. "
        "Incluye: Datos recopilados, Uso, Cookies, Derechos del usuario, Contacto. "
        "Tono: formal, transparente. Máximo 600 palabras."
    ),
    "nda": (
        "Genera un NDA (Acuerdo de Confidencialidad) entre '{party_a}' y '{party_b}' "
        "para el proyecto '{project}'. Jurisdicción: {jurisdiction}. "
        "Incluye: Información confidencial, Obligaciones, Excepciones, Duración, Penalidades. "
        "Tono: legal, formal. Máximo 500 palabras."
    ),
    "refund_policy": (
        "Genera una Política de Reembolsos para '{product}' de '{company}'. "
        "Plazos: {refund_days} días. Condiciones especiales: {conditions}. "
        "Tono: claro, justo, en español. Máximo 300 palabras."
    ),
}


# ─── Modelos ──────────────────────────────────────────────────────────────────

class LegalDocIn(BaseModel):
    doc_type: str = Field(..., description="tos|privacy_policy|contract|nda|refund_policy")
    tenant_id: Optional[str] = None
    company: str
    product: str
    jurisdiction: str = "generic"
    extra_params: dict = Field(default_factory=dict,
                                description="Parámetros extra según doc_type")

    def validate_type(self) -> None:
        if self.doc_type not in DOC_TYPES:
            raise ValueError(f"doc_type inválido: {self.doc_type}")


class ContractIn(BaseModel):
    title: str
    tenant_id: Optional[str] = None
    party_a: str
    party_b: str
    terms: str
    jurisdiction: str = "generic"
    valid_days: int = 30


class ComplianceCheckIn(BaseModel):
    tenant_id: Optional[str] = None
    jurisdiction: str = "eu"
    features: List[str] = Field(default_factory=list,
                                 description="Features a validar: payments, data_storage, ai_processing")


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e6_legal_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E6",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e6] audit failed: {exc}")


# ─── Business logic ───────────────────────────────────────────────────────────

async def _generate_legal_doc(doc_type: str, company: str, product: str,
                               jurisdiction: str, extra: dict, actor: str,
                               tenant_id: str = "") -> dict:
    template = TEMPLATES.get(doc_type)
    if not template:
        # Generar con prompt genérico para tipos sin template específico
        template = (
            f"Genera un documento legal de tipo '{doc_type}' para la empresa '{{company}}' "
            f"y el producto '{{product}}'. Jurisdicción: {{jurisdiction}}. "
            f"Tono profesional, formal, en español."
        )

    prompt = template.format(
        company=company, product=product, jurisdiction=jurisdiction,
        **{k: str(v) for k, v in extra.items()}
    )

    client, model = llm_router.get_client("low")
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Eres un abogado especializado en derecho digital y SaaS. Generas documentos legales precisos y profesionales en español."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.3,
        )
        content_html = resp.choices[0].message.content or ""
    except Exception as exc:
        logger.warning(f"[e6] LLM failed: {exc}")
        content_html = f"[Documento {doc_type} para {product} — requiere revisión manual]"

    doc_id = "leg_" + secrets.token_urlsafe(8)
    doc = {
        "id": doc_id,
        "doc_type": doc_type,
        "tenant_id": tenant_id,
        "company": company,
        "product": product,
        "jurisdiction": jurisdiction,
        "content": content_html,
        "version": "1.0",
        "status": "draft",
        "model_used": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "signed_at": None,
        "signed_by_ip": None,
    }
    await _db().e6_legal_docs.insert_one(doc)
    await _audit("doc_generated", actor, {"doc_id": doc_id, "doc_type": doc_type}, tenant_id)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _create_contract(data: dict, actor: str) -> dict:
    contract_id = "con_" + secrets.token_urlsafe(8)
    doc = {
        "id": contract_id,
        "title": data["title"],
        "tenant_id": data.get("tenant_id", ""),
        "party_a": data["party_a"],
        "party_b": data["party_b"],
        "terms": data["terms"],
        "jurisdiction": data.get("jurisdiction", "generic"),
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
        "signed_at": None,
        "expires_at": None,
    }
    await _db().e6_contracts.insert_one(doc)
    await _audit("contract_created", actor, {"contract_id": contract_id}, data.get("tenant_id", ""))
    return {k: v for k, v in doc.items() if k != "_id"}


async def _compliance_check(features: list, jurisdiction: str, tenant_id: str, actor: str) -> dict:
    issues = []
    recommendations = []

    if jurisdiction in ("eu", "spain") and "data_storage" in features:
        recommendations.append("GDPR: Documentar base legal de tratamiento de datos personales")
        recommendations.append("GDPR: Implementar registro de actividades de tratamiento")

    if "payments" in features:
        recommendations.append("PCI-DSS: No almacenar datos de tarjetas en texto plano")
        recommendations.append("Stripe/PayPal: Usar tokenización de pagos")

    if "ai_processing" in features:
        recommendations.append("EU AI Act: Categorizar riesgo del sistema de IA")
        if jurisdiction in ("eu", "spain"):
            recommendations.append("GDPR Art. 22: Informar al usuario sobre decisiones automatizadas")

    check_id = "chk_" + secrets.token_urlsafe(8)
    doc = {
        "id": check_id,
        "tenant_id": tenant_id,
        "jurisdiction": jurisdiction,
        "features_checked": features,
        "issues": issues,
        "recommendations": recommendations,
        "compliant": len(issues) == 0,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checked_by": actor,
    }
    await _db().e6_compliance.insert_one(doc)
    await _audit("compliance_checked", actor, {"check_id": check_id, "jurisdiction": jurisdiction}, tenant_id)
    return {k: v for k, v in doc.items() if k != "_id"}


# ─── Tool functions ────────────────────────────────────────────────────────────

async def tool_tos_generator(company: str, product: str, jurisdiction: str = "generic",
                              tenant_id: str = "") -> dict:
    return await _generate_legal_doc("tos", company, product, jurisdiction, {}, "e1_tool", tenant_id)


async def tool_privacy_builder(company: str, product: str, jurisdiction: str = "generic",
                                data_collected: str = "email, uso de plataforma",
                                tenant_id: str = "") -> dict:
    return await _generate_legal_doc("privacy_policy", company, product, jurisdiction,
                                      {"data_collected": data_collected}, "e1_tool", tenant_id)


async def tool_contract_builder(title: str, party_a: str, party_b: str,
                                 terms: str, jurisdiction: str = "generic",
                                 tenant_id: str = "") -> dict:
    return await _create_contract(
        {"title": title, "party_a": party_a, "party_b": party_b,
         "terms": terms, "jurisdiction": jurisdiction, "tenant_id": tenant_id},
        actor="e1_tool"
    )


async def tool_compliance_checker(features: list, jurisdiction: str = "eu",
                                   tenant_id: str = "") -> dict:
    return await _compliance_check(features, jurisdiction, tenant_id, "e1_tool")


async def tool_gdpr_audit(tenant_id: str, data_flows: list = None) -> dict:
    features = ["data_storage", "ai_processing"] + (data_flows or [])
    return await _compliance_check(features, "eu", tenant_id, "e1_tool")


# ─── FastAPI endpoints ─────────────────────────────────────────────────────────

@router.post("/docs/generate")
async def generate_doc(data: LegalDocIn, user: dict = Depends(auth.get_current_user)):
    return await _generate_legal_doc(
        data.doc_type, data.company, data.product, data.jurisdiction,
        data.extra_params, user["email"], data.tenant_id or ""
    )


@router.get("/docs")
async def list_docs(tenant_id: Optional[str] = None,
                     user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e6_legal_docs.find(q, {"_id": 0, "content": 0}).sort("created_at", -1).limit(100)
    return {"docs": [d async for d in cur]}


@router.get("/docs/{doc_id}")
async def get_doc(doc_id: str, user: dict = Depends(auth.get_current_user)):
    doc = await _db().e6_legal_docs.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.post("/contracts")
async def create_contract(data: ContractIn, user: dict = Depends(auth.get_current_user)):
    return await _create_contract(data.model_dump(), actor=user["email"])


@router.get("/contracts")
async def list_contracts(tenant_id: Optional[str] = None,
                          user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e6_contracts.find(q, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"contracts": [c async for c in cur]}


@router.post("/compliance/check")
async def compliance_check(data: ComplianceCheckIn, user: dict = Depends(auth.get_current_user)):
    return await _compliance_check(data.features, data.jurisdiction,
                                    data.tenant_id or "", user["email"])


@router.get("/compliance")
async def list_compliance(tenant_id: Optional[str] = None,
                           user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e6_compliance.find(q, {"_id": 0}).sort("checked_at", -1).limit(50)
    return {"checks": [c async for c in cur]}
