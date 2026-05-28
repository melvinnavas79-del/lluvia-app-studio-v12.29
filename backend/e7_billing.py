"""
E7 — Billing / Subscriptions / Payments
Arquitectura multi-provider: BillingEngine agnóstico del provider de pagos.

Phase 1 (activo): PayPal Business — suscripciones recurrentes, webhooks reales,
                  activación automática de tenants, caché de billing plans.
Phase 2 (prep):   Stripe — mismo contrato de interfaz, activar con STRIPE_SECRET_KEY.
Manual:           Activación enterprise sin pago externo.

Reutiliza paypal_integration._paypal_env() y _verify_paypal_signature() sin duplicar.
No toca console.py, paypal_integration.py, ni E1.

ENV vars:
  PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE (sandbox|live)  ← ya configuradas
  PAYPAL_WEBHOOK_ID                                             ← ya configurada
  PAYPAL_PRODUCT_ID   (opcional — si no está, se auto-crea en PayPal)
  PAYPAL_RETURN_URL   ← URL de éxito tras aprobación del plan
  PAYPAL_CANCEL_URL   ← URL de cancelación
  STRIPE_SECRET_KEY   (Phase 2)
  STRIPE_WEBHOOK_SECRET (Phase 2)
"""
import os
import json
import logging
import secrets
import asyncio
import requests as _requests
from pymongo.errors import DuplicateKeyError as _DuplicateKeyError
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import auth
from e9_emitters import track_call

logger = logging.getLogger("e7_billing")
router = APIRouter(prefix="/e7", tags=["E7-Billing"])
_db_ref: dict = {"db": None}


def set_db(db) -> None:
    _db_ref["db"] = db


def _db():
    return _db_ref["db"]


# ─── Planes de negocio (independientes del provider) ──────────────────────────

BILLING_PLANS = {
    "starter_monthly": {
        "name": "Starter Mensual", "amount_usd": 29.00, "currency": "USD",
        "interval": "MONTH", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Starter (mensual)",
    },
    "pro_monthly": {
        "name": "Pro Mensual", "amount_usd": 99.00, "currency": "USD",
        "interval": "MONTH", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Pro (mensual)",
    },
    "agency_monthly": {
        "name": "Agency Mensual", "amount_usd": 299.00, "currency": "USD",
        "interval": "MONTH", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Agency (mensual)",
    },
    "starter_annual": {
        "name": "Starter Anual", "amount_usd": 249.00, "currency": "USD",
        "interval": "YEAR", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Starter (anual)",
    },
    "pro_annual": {
        "name": "Pro Anual", "amount_usd": 899.00, "currency": "USD",
        "interval": "YEAR", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Pro (anual)",
    },
    "agency_annual": {
        "name": "Agency Anual", "amount_usd": 2490.00, "currency": "USD",
        "interval": "YEAR", "interval_count": 1,
        "description": "Lluvia App Studio — Plan Agency (anual)",
    },
    "enterprise_custom": {
        "name": "Enterprise Custom", "amount_usd": 0.00, "currency": "USD",
        "interval": "MONTH", "interval_count": 1,
        "description": "Lluvia App Studio — Enterprise (precio custom)",
    },
}

# Plan key → E5 plan name (para activar tenant con el plan correcto)
PLAN_TO_E5 = {
    "starter_monthly": "starter",
    "starter_annual":  "starter",
    "pro_monthly":     "pro",
    "pro_annual":      "pro",
    "agency_monthly":  "agency",
    "agency_annual":   "agency",
    "enterprise_custom": "enterprise",
}

SUB_STATUSES = ["pending_approval", "active", "cancelled", "suspended", "expired", "failed"]
PROVIDERS = ["paypal", "stripe", "manual"]


# ─── Audit log ────────────────────────────────────────────────────────────────

async def _audit(action: str, actor: str, detail: dict, tenant_id: str = "") -> None:
    try:
        await _db().e7_billing_logs.insert_one({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": "E7",
            "action": action,
            "actor": actor,
            "tenant_id": tenant_id,
            "detail": detail,
        })
    except Exception as exc:
        logger.warning(f"[e7] audit failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# ABSTRACT PAYMENT PROVIDER
# ═══════════════════════════════════════════════════════════════════════════════

class PaymentProvider(ABC):
    """Interfaz común para todos los providers de pago."""

    @abstractmethod
    async def get_or_create_billing_plan(self, plan_key: str) -> str:
        """Retorna provider_plan_id (cacheado en e7_billing_plans)."""

    @abstractmethod
    async def create_subscription(self, provider_plan_id: str,
                                   billing_email: str,
                                   return_url: str,
                                   cancel_url: str,
                                   custom_id: str) -> dict:
        """
        Retorna {
          provider_subscription_id, approval_url, status
        }
        """

    @abstractmethod
    async def cancel_subscription(self, provider_subscription_id: str,
                                   reason: str) -> bool:
        """Cancela en el provider. Retorna True si OK."""

    @abstractmethod
    async def get_subscription_status(self, provider_subscription_id: str) -> dict:
        """Retorna {status, next_billing_date, ...} desde el provider."""

    @abstractmethod
    async def verify_webhook(self, headers: dict, body: bytes) -> bool:
        """Valida la firma del webhook del provider."""

    @abstractmethod
    async def parse_webhook_event(self, body: bytes) -> dict:
        """
        Retorna {
          event_type: "subscription_activated" | "subscription_cancelled" |
                      "payment_completed" | "subscription_suspended" | "unknown",
          provider_subscription_id,
          amount_usd,
          currency,
          raw_event_type,
        }
        """


# ═══════════════════════════════════════════════════════════════════════════════
# PAYPAL PROVIDER — PHASE 1 (REAL)
# ═══════════════════════════════════════════════════════════════════════════════

class PayPalProvider(PaymentProvider):
    """
    Implementación real de PayPal Business.
    Reutiliza _paypal_env() y _verify_paypal_signature() de paypal_integration.py.
    Usa PayPal Billing Plans v1 API para suscripciones recurrentes.
    """

    def _env(self) -> tuple[str, str, str]:
        from paypal_integration import _paypal_env
        return _paypal_env()

    def _token(self) -> str:
        from paypal_integration import _access_token
        return _access_token()

    async def _async_token(self) -> str:
        return await asyncio.to_thread(self._token)

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        }

    async def _post(self, path: str, payload: dict) -> dict:
        base, _, _ = self._env()
        token = await self._async_token()

        def _sync():
            r = _requests.post(
                f"{base}{path}",
                json=payload,
                headers=self._headers(token),
                timeout=20,
            )
            return r

        resp = await asyncio.to_thread(_sync)
        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"PayPal API error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json() if resp.content else {}

    async def _get(self, path: str) -> dict:
        base, _, _ = self._env()
        token = await self._async_token()

        def _sync():
            return _requests.get(
                f"{base}{path}",
                headers=self._headers(token),
                timeout=20,
            )

        resp = await asyncio.to_thread(_sync)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"PayPal GET error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    async def _patch(self, path: str, payload: list) -> bool:
        base, _, _ = self._env()
        token = await self._async_token()

        def _sync():
            return _requests.patch(
                f"{base}{path}",
                json=payload,
                headers=self._headers(token),
                timeout=20,
            )

        resp = await asyncio.to_thread(_sync)
        return resp.status_code in (200, 204)

    async def _get_or_create_product(self) -> str:
        """Obtiene PAYPAL_PRODUCT_ID del env o crea un producto en PayPal."""
        product_id = os.getenv("PAYPAL_PRODUCT_ID", "").strip()
        if product_id:
            return product_id

        # Crear producto si no está configurado
        cached = await _db().e7_billing_plans.find_one({"_type": "paypal_product"})
        if cached:
            return cached["product_id"]

        data = await self._post("/v1/catalogs/products", {
            "name": "Lluvia App Studio",
            "description": "Plataforma SaaS de agentes IA white-label",
            "type": "SERVICE",
            "category": "SOFTWARE",
        })
        product_id = data["id"]
        await _db().e7_billing_plans.insert_one({
            "_type": "paypal_product",
            "product_id": product_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[e7/paypal] Producto creado: {product_id} — guardalo como PAYPAL_PRODUCT_ID")
        return product_id

    async def get_or_create_billing_plan(self, plan_key: str) -> str:
        """Retorna PayPal plan_id para el plan_key dado. Cachea en MongoDB.
        Race-safe: uses upsert with retry to handle concurrent plan creation."""
        # Buscar en caché
        cached = await _db().e7_billing_plans.find_one(
            {"plan_key": plan_key, "provider": "paypal", "status": "ACTIVE"}
        )
        if cached:
            return cached["provider_plan_id"]

        plan = BILLING_PLANS.get(plan_key)
        if not plan:
            raise HTTPException(status_code=400, detail=f"Plan inválido: {plan_key}")
        if plan["amount_usd"] == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Plan '{plan_key}' es custom/manual — no crea billing plan en PayPal"
            )

        product_id = await self._get_or_create_product()

        paypal_plan = await self._post("/v1/billing/plans", {
            "product_id": product_id,
            "name": plan["name"],
            "description": plan["description"],
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {
                        "interval_unit": plan["interval"],
                        "interval_count": plan["interval_count"],
                    },
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,  # 0 = infinito
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": f"{plan['amount_usd']:.2f}",
                            "currency_code": plan["currency"],
                        }
                    },
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
        })

        provider_plan_id = paypal_plan["id"]
        try:
            await _db().e7_billing_plans.insert_one({
                "plan_key": plan_key,
                "provider": "paypal",
                "provider_plan_id": provider_plan_id,
                "amount_usd": plan["amount_usd"],
                "currency": plan["currency"],
                "interval": plan["interval"],
                "status": "ACTIVE",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except _DuplicateKeyError:
            # Race: another concurrent request already inserted. Use that one.
            winner = await _db().e7_billing_plans.find_one(
                {"plan_key": plan_key, "provider": "paypal", "status": "ACTIVE"}
            )
            if winner:
                logger.info(f"[e7/paypal] Race duplicate plan_key={plan_key} — using existing {winner['provider_plan_id']}")
                return winner["provider_plan_id"]
        logger.info(f"[e7/paypal] Billing plan creado: {provider_plan_id} para {plan_key}")
        return provider_plan_id

    async def create_subscription(self, provider_plan_id: str,
                                   billing_email: str,
                                   return_url: str,
                                   cancel_url: str,
                                   custom_id: str) -> dict:
        """Crea suscripción en PayPal. custom_id = sub_id interno para rastreo en webhook."""
        payload: dict = {
            "plan_id": provider_plan_id,
            "custom_id": custom_id,
            "application_context": {
                "brand_name": "Lluvia App Studio",
                "locale": "es-419",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        if billing_email:
            payload["subscriber"] = {"email_address": billing_email}

        data = await self._post("/v1/billing/subscriptions", payload)
        approval_url = next(
            (l["href"] for l in data.get("links", []) if l.get("rel") == "approve"),
            None
        )
        return {
            "provider_subscription_id": data["id"],
            "approval_url": approval_url,
            "status": data.get("status", "APPROVAL_PENDING"),
        }

    async def cancel_subscription(self, provider_subscription_id: str, reason: str) -> bool:
        base, _, _ = self._env()
        token = await self._async_token()

        def _sync():
            return _requests.post(
                f"{base}/v1/billing/subscriptions/{provider_subscription_id}/cancel",
                json={"reason": reason or "Cancelado por el usuario"},
                headers=self._headers(token),
                timeout=20,
            )

        resp = await asyncio.to_thread(_sync)
        return resp.status_code == 204

    async def get_subscription_status(self, provider_subscription_id: str) -> dict:
        data = await self._get(f"/v1/billing/subscriptions/{provider_subscription_id}")
        return {
            "provider_status": data.get("status"),
            "next_billing_time": data.get("billing_info", {}).get("next_billing_time"),
            "last_payment": data.get("billing_info", {}).get("last_payment"),
            "cycles_completed": data.get("billing_info", {}).get("cycles_completed", 0),
            "raw": data,
        }

    async def refund_payment(self, sale_id: str, amount_usd: float, currency: str,
                              reason: str = "") -> dict:
        """Refund a completed PayPal sale. sale_id is the PayPal transaction ID."""
        base, _, _ = self._env()
        token = await self._async_token()
        payload: dict = {"note_to_payer": reason or "Reembolso procesado"}
        if amount_usd > 0:
            payload["amount"] = {"total": f"{amount_usd:.2f}", "currency": currency}

        def _sync():
            return _requests.post(
                f"{base}/v1/payments/sale/{sale_id}/refund",
                json=payload,
                headers=self._headers(token),
                timeout=20,
            )

        resp = await asyncio.to_thread(_sync)
        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"PayPal refund error {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        return {
            "refund_id": data.get("id", ""),
            "status": data.get("state", ""),
            "amount_usd": float(data.get("amount", {}).get("total", amount_usd)),
        }

    async def verify_webhook(self, headers: dict, body: bytes) -> bool:
        from paypal_integration import _verify_paypal_signature
        return await asyncio.to_thread(_verify_paypal_signature, headers, body)

    async def parse_webhook_event(self, body: bytes) -> dict:
        try:
            event = json.loads(body.decode("utf-8"))
        except Exception:
            return {"event_type": "unknown", "provider_subscription_id": "", "amount_usd": 0}

        raw_type = event.get("event_type", "")
        resource = event.get("resource", {})

        # Mapeo de eventos PayPal → evento interno
        EVENT_MAP = {
            "BILLING.SUBSCRIPTION.ACTIVATED":  "subscription_activated",
            "BILLING.SUBSCRIPTION.CANCELLED":  "subscription_cancelled",
            "BILLING.SUBSCRIPTION.SUSPENDED":  "subscription_suspended",
            "BILLING.SUBSCRIPTION.EXPIRED":    "subscription_expired",
            "PAYMENT.SALE.COMPLETED":          "payment_completed",
            "PAYMENT.SALE.REFUNDED":           "payment_refunded",
        }

        event_type = EVENT_MAP.get(raw_type, "unknown")

        # provider_subscription_id puede estar en distintos campos según el evento
        sub_id = (
            resource.get("id") if raw_type.startswith("BILLING.SUBSCRIPTION")
            else resource.get("billing_agreement_id", "")
        )

        # custom_id = nuestro sub_id interno (lo seteamos al crear la suscripción)
        custom_id = resource.get("custom_id", "") or resource.get("custom", "")

        # Monto pagado
        amount = 0.0
        currency = "USD"
        if raw_type == "PAYMENT.SALE.COMPLETED":
            amt_obj = resource.get("amount", {})
            try:
                amount = float(amt_obj.get("total", 0))
                currency = amt_obj.get("currency", "USD")
            except (ValueError, TypeError):
                pass

        return {
            "event_type": event_type,
            "raw_event_type": raw_type,
            "provider_subscription_id": sub_id,
            "custom_id": custom_id,
            "amount_usd": amount,
            "currency": currency,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# STRIPE PROVIDER — PHASE 2 (REAL when STRIPE_SECRET_KEY configured)
# ═══════════════════════════════════════════════════════════════════════════════

class StripeProvider(PaymentProvider):
    """
    Stripe como provider secundario — Phase 2.
    Misma interfaz que PayPalProvider.
    Activar configurando STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET.

    Flujo checkout:
      1. create_subscription() → Checkout Session (status=pending_approval)
      2. checkout.session.completed webhook → actualiza provider_subscription_id real
      3. invoice.paid, customer.subscription.* → lifecycle events
    """

    def _require_stripe(self) -> str:
        """Retorna STRIPE_SECRET_KEY o lanza 503. Lee env en tiempo de ejecución."""
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key:
            raise HTTPException(
                status_code=503,
                detail="Stripe Phase 2 — configurar STRIPE_SECRET_KEY para activar"
            )
        return key

    async def get_or_create_billing_plan(self, plan_key: str) -> str:
        stripe_key = self._require_stripe()
        cached = await _db().e7_billing_plans.find_one(
            {"plan_key": plan_key, "provider": "stripe", "status": "active"}
        )
        if cached:
            return cached["provider_plan_id"]
        plan = BILLING_PLANS.get(plan_key)
        if not plan:
            raise HTTPException(status_code=400, detail=f"Plan inválido: {plan_key}")
        import stripe
        stripe.api_key = stripe_key
        interval = "month" if plan["interval"] == "MONTH" else "year"
        price = await asyncio.to_thread(
            lambda: stripe.Price.create(
                unit_amount=int(plan["amount_usd"] * 100),
                currency=plan["currency"].lower(),
                recurring={"interval": interval},
                product_data={"name": plan["name"]},
            )
        )
        await _db().e7_billing_plans.insert_one({
            "plan_key": plan_key, "provider": "stripe",
            "provider_plan_id": price["id"], "status": "active",
            "amount_usd": plan["amount_usd"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return price["id"]

    async def create_subscription(self, provider_plan_id, billing_email,
                                   return_url, cancel_url, custom_id) -> dict:
        stripe_key = self._require_stripe()
        import stripe
        stripe.api_key = stripe_key

        # Create customer first (idempotent via custom_id lookup)
        customer = await asyncio.to_thread(
            lambda: stripe.Customer.create(
                email=billing_email,
                metadata={"custom_id": custom_id},
            )
        )
        # Create Checkout Session — session.subscription is None at creation time.
        # It will be populated after the user completes checkout.
        # We store the session ID now and update to real subscription_id via
        # checkout.session.completed webhook.
        session = await asyncio.to_thread(
            lambda: stripe.checkout.Session.create(
                customer=customer["id"],
                mode="subscription",
                line_items=[{"price": provider_plan_id, "quantity": 1}],
                success_url=return_url,
                cancel_url=cancel_url,
                metadata={"custom_id": custom_id},
            )
        )
        return {
            "provider_subscription_id": session["id"],  # checkout session ID
            "approval_url": session["url"],
            "status": "pending_approval",
        }

    async def cancel_subscription(self, provider_subscription_id, reason) -> bool:
        stripe_key = self._require_stripe()
        import stripe
        stripe.api_key = stripe_key
        # Works for subscription IDs (sub_xxx); session IDs (cs_xxx) can't be cancelled
        if provider_subscription_id.startswith("sub_"):
            await asyncio.to_thread(
                lambda: stripe.Subscription.cancel(provider_subscription_id)
            )
        return True

    async def get_subscription_status(self, provider_subscription_id) -> dict:
        stripe_key = self._require_stripe()
        import stripe
        stripe.api_key = stripe_key
        if provider_subscription_id.startswith("sub_"):
            sub = await asyncio.to_thread(
                lambda: stripe.Subscription.retrieve(provider_subscription_id)
            )
            return {"provider_status": sub["status"], "raw": dict(sub)}
        # Checkout session — pendiente de completarse
        return {"provider_status": "pending_approval",
                "note": "Checkout session no completada aún"}

    async def verify_webhook(self, headers, body) -> bool:
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        if not webhook_secret:
            return False
        try:
            import stripe
            stripe.Webhook.construct_event(
                body, headers.get("stripe-signature", ""), webhook_secret
            )
            return True
        except Exception:
            return False

    async def parse_webhook_event(self, body) -> dict:
        # Firma ya verificada en verify_webhook — parsear directamente
        try:
            event = json.loads(body.decode("utf-8"))
        except Exception:
            return {"event_type": "unknown", "provider_subscription_id": "",
                    "amount_usd": 0, "stripe_event_id": ""}

        raw_type = event.get("type", "")
        obj      = event.get("data", {}).get("object", {})

        EVENT_MAP = {
            "customer.subscription.created":   "subscription_activated",
            "customer.subscription.updated":   "subscription_updated",
            "customer.subscription.deleted":   "subscription_cancelled",
            "invoice.paid":                    "payment_completed",
            "invoice.payment_failed":          "payment_failed",
            "checkout.session.completed":      "checkout_session_completed",
        }

        # Extraer subscription ID según tipo de evento
        if raw_type == "checkout.session.completed":
            # obj.subscription = real sub ID after checkout; obj.id = session ID
            sub_id = obj.get("subscription") or obj.get("id", "")
        else:
            sub_id = obj.get("subscription") or obj.get("id", "")

        # custom_id = nuestro sub_id interno (se pasa en metadata al crear)
        custom_id = (obj.get("metadata") or {}).get("custom_id", "")

        amount_usd = 0.0
        if raw_type == "invoice.paid":
            amount_usd = obj.get("amount_paid", 0) / 100

        return {
            "event_type":              EVENT_MAP.get(raw_type, "unknown"),
            "raw_event_type":          raw_type,
            "provider_subscription_id": sub_id,
            "custom_id":               custom_id,
            "amount_usd":              amount_usd,
            "currency":                obj.get("currency", "usd").upper(),
            "stripe_event_id":         event.get("id", ""),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL PROVIDER — Enterprise / ventas directas
# ═══════════════════════════════════════════════════════════════════════════════

class ManualProvider(PaymentProvider):
    """Activación sin payment gateway — para enterprise, demos o ventas directas."""

    async def get_or_create_billing_plan(self, plan_key: str) -> str:
        return f"manual::{plan_key}"

    async def create_subscription(self, provider_plan_id, billing_email,
                                   return_url, cancel_url, custom_id) -> dict:
        return {
            "provider_subscription_id": f"manual_{secrets.token_urlsafe(8)}",
            "approval_url": None,
            "status": "ACTIVE",  # activación inmediata
        }

    async def cancel_subscription(self, provider_subscription_id, reason) -> bool:
        return True

    async def get_subscription_status(self, provider_subscription_id) -> dict:
        return {"provider_status": "ACTIVE", "note": "Manual provider — sin payment gateway"}

    async def verify_webhook(self, headers, body) -> bool:
        return False  # no hay webhooks en manual

    async def parse_webhook_event(self, body) -> dict:
        return {"event_type": "unknown", "provider_subscription_id": "", "amount_usd": 0}


# ─── Factory ──────────────────────────────────────────────────────────────────

def get_provider(key: str) -> PaymentProvider:
    if key == "paypal":
        return PayPalProvider()
    if key == "stripe":
        return StripeProvider()
    if key == "manual":
        return ManualProvider()
    raise HTTPException(status_code=400, detail=f"Provider inválido: '{key}'. Válidos: {PROVIDERS}")


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING ENGINE — provider-agnostic
# ═══════════════════════════════════════════════════════════════════════════════

async def engine_subscribe(tenant_id: str, plan_key: str, payment_provider: str,
                            billing_email: str, actor: str) -> dict:
    """
    Crea una suscripción en el provider seleccionado.
    Retorna el sub_id interno + approval_url (si aplica) para redirigir al usuario.
    """
    if plan_key not in BILLING_PLANS:
        raise HTTPException(status_code=400, detail=f"Plan inválido: {plan_key}")
    if payment_provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider inválido: {payment_provider}")

    # Genérico primero, con fallback a las vars PayPal legacy para retrocompat.
    return_url = os.getenv("BILLING_RETURN_URL",
                           os.getenv("PAYPAL_RETURN_URL", "https://lluvia.app/billing/success"))
    cancel_url = os.getenv("BILLING_CANCEL_URL",
                           os.getenv("PAYPAL_CANCEL_URL", "https://lluvia.app/billing/cancel"))

    sub_id = "sub_" + secrets.token_urlsafe(10)
    provider = get_provider(payment_provider)

    # Obtener / crear billing plan en el provider
    provider_plan_id = await provider.get_or_create_billing_plan(plan_key)

    # Crear suscripción en el provider
    result = await provider.create_subscription(
        provider_plan_id, billing_email, return_url, cancel_url, custom_id=sub_id
    )

    plan_info = BILLING_PLANS[plan_key]
    now = datetime.now(timezone.utc)

    doc = {
        "id": sub_id,
        "tenant_id": tenant_id,
        "plan_key": plan_key,
        "e5_plan": PLAN_TO_E5.get(plan_key, "starter"),
        "payment_provider": payment_provider,
        "provider_plan_id": provider_plan_id,
        "provider_subscription_id": result["provider_subscription_id"],
        "billing_email": billing_email,
        "amount_usd": plan_info["amount_usd"],
        "currency": plan_info["currency"],
        "billing_interval": plan_info["interval"],
        "approval_url": result.get("approval_url"),
        "status": "active" if result["status"] == "ACTIVE" else "pending_approval",
        # active_slot is present on active/pending docs so the unique sparse index
        # (tenant_id, active_slot) blocks concurrent double-subscribe atomically.
        # It is $unset when the subscription is cancelled or expires.
        "active_slot": "1",
        "created_at": now.isoformat(),
        "created_by": actor,
        "activated_at": now.isoformat() if result["status"] == "ACTIVE" else None,
        "cancelled_at": None,
        "next_billing_date": None,
    }
    try:
        await _db().e7_subscriptions.insert_one(doc)
    except _DuplicateKeyError:
        # Another concurrent call already claimed the active slot for this tenant
        existing = await _db().e7_subscriptions.find_one(
            {"tenant_id": tenant_id, "active_slot": "1"}, {"_id": 0}
        )
        if existing:
            logger.info(f"[e7] concurrent subscribe blocked for tenant={tenant_id}, existing sub={existing.get('id')}")
            return {**existing, "idempotent": True}
        raise

    # Si es manual → activar tenant inmediatamente
    if payment_provider == "manual" and result["status"] == "ACTIVE":
        await _auto_activate_tenant(sub_id, tenant_id, plan_key, 0.0, "USD", actor)

    await _audit("subscription_created", actor,
                  {"sub_id": sub_id, "tenant_id": tenant_id,
                   "plan_key": plan_key, "provider": payment_provider},
                  tenant_id)

    return {k: v for k, v in doc.items() if k != "_id"}


async def engine_cancel(sub_id: str, reason: str, actor: str) -> dict:
    """Cancela suscripción en el provider y marca en BD."""
    doc = await _db().e7_subscriptions.find_one({"id": sub_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")

    provider = get_provider(doc["payment_provider"])
    if doc.get("provider_subscription_id"):
        await provider.cancel_subscription(doc["provider_subscription_id"], reason)

    now = datetime.now(timezone.utc).isoformat()
    await _db().e7_subscriptions.update_one(
        {"id": sub_id},
        {"$set": {"status": "cancelled", "cancelled_at": now},
         "$unset": {"active_slot": ""}}
    )
    await _audit("subscription_cancelled", actor,
                  {"sub_id": sub_id, "reason": reason}, doc.get("tenant_id", ""))
    return {"sub_id": sub_id, "status": "cancelled", "cancelled_at": now}


async def engine_record_payment(sub_id: str, amount_usd: float, currency: str,
                                 provider_txn_id: str, provider: str, actor: str = "webhook") -> dict:
    """Registra un pago recibido. Inmutable."""
    pay_id = "pay_" + secrets.token_urlsafe(10)
    doc_sub = await _db().e7_subscriptions.find_one({"id": sub_id}, {"_id": 0})
    tenant_id = doc_sub.get("tenant_id", "") if doc_sub else ""

    doc = {
        "id": pay_id,
        "sub_id": sub_id,
        "tenant_id": tenant_id,
        "payment_provider": provider,
        "provider_txn_id": provider_txn_id,
        "amount_usd": amount_usd,
        "currency": currency,
        "status": "completed",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db().e7_payments.insert_one(doc)
    await _audit("payment_recorded", actor,
                  {"pay_id": pay_id, "sub_id": sub_id,
                   "amount_usd": amount_usd, "txn_id": provider_txn_id},
                  tenant_id)
    return {k: v for k, v in doc.items() if k != "_id"}


async def _auto_activate_tenant(sub_id: str, tenant_id: str, plan_key: str,
                                 amount_usd: float, currency: str, actor: str) -> None:
    """Activa el tenant en E5 al recibir pago confirmado. No lanza excepción si falla."""
    try:
        import e5_whitelabel as e5
        e5_plan = PLAN_TO_E5.get(plan_key, "starter")
        # Actualizar plan del tenant en E5
        await _db().e5_tenants.update_one(
            {"id": tenant_id},
            {"$set": {
                "plan": e5_plan,
                "status": "active",
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }}
        )
        await _audit("tenant_auto_activated", actor,
                      {"tenant_id": tenant_id, "plan": e5_plan,
                       "sub_id": sub_id, "amount_usd": amount_usd},
                      tenant_id)
        logger.info(f"[e7] Tenant {tenant_id} activado automáticamente → plan {e5_plan}")
    except Exception as exc:
        logger.error(f"[e7] auto_activate_tenant falló para {tenant_id}: {exc}")
        await _audit("tenant_auto_activation_failed", actor,
                      {"tenant_id": tenant_id, "error": str(exc)}, tenant_id)


async def engine_billing_summary(tenant_id: str) -> dict:
    """Resumen de billing para un tenant."""
    sub = await _db().e7_subscriptions.find_one(
        {"tenant_id": tenant_id, "status": {"$in": ["active", "pending_approval"]}},
        {"_id": 0}
    )
    payments = [p async for p in _db().e7_payments.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("received_at", -1).limit(10)]
    invoices = [i async for i in _db().e7_invoices.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ).sort("created_at", -1).limit(10)]

    total_paid = sum(p.get("amount_usd", 0) for p in payments)
    return {
        "tenant_id": tenant_id,
        "active_subscription": sub,
        "payments_count": len(payments),
        "total_paid_usd": round(total_paid, 2),
        "recent_payments": payments,
        "recent_invoices": invoices,
        "available_providers": PROVIDERS,
    }


# ─── Usage metering ───────────────────────────────────────────────────────────

async def engine_track_usage(tenant_id: str, metric: str, value: float,
                              period: str = "") -> dict:
    now = datetime.now(timezone.utc)
    period = period or now.strftime("%Y-%m")
    await _db().e7_usage.update_one(
        {"tenant_id": tenant_id, "metric": metric, "period": period},
        {"$inc": {"value": value}, "$set": {"last_updated": now.isoformat()}},
        upsert=True,
    )
    return {"tenant_id": tenant_id, "metric": metric, "period": period, "added": value}


# ─── Invoice generator ────────────────────────────────────────────────────────

async def engine_generate_invoice(tenant_id: str, items: list,
                                   billing_email: str, due_days: int,
                                   currency: str, actor: str) -> dict:
    inv_id = "inv_" + secrets.token_urlsafe(10)
    total = sum(i.get("amount_usd", 0) * i.get("quantity", 1) for i in items)
    due = (datetime.now(timezone.utc) + timedelta(days=due_days)).isoformat()
    doc = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "billing_email": billing_email,
        "items": items,
        "subtotal_usd": round(total, 2),
        "tax_usd": 0.0,
        "total_usd": round(total, 2),
        "currency": currency,
        "status": "draft",
        "due_date": due,
        "paid_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e7_invoices.insert_one(doc)
    await _audit("invoice_created", actor,
                  {"inv_id": inv_id, "total_usd": total}, tenant_id)
    return {k: v for k, v in doc.items() if k != "_id"}


# ─── Webhook handler central ──────────────────────────────────────────────────

async def handle_provider_webhook(provider_key: str, headers: dict, body: bytes) -> dict:
    """
    Punto de entrada único para webhooks de cualquier provider.
    1. Valida firma → 403 si inválida.
    2. Parsea evento → identifica tipo.
    3. Ejecuta acción en BD (activar, cancelar, registrar pago).
    4. Activa tenant en E5 si pago confirmado.
    """
    provider = get_provider(provider_key)

    valid = await provider.verify_webhook(headers, body)
    if not valid:
        raise HTTPException(status_code=403, detail=f"Firma webhook {provider_key} inválida")

    event = await provider.parse_webhook_event(body)
    event_type      = event.get("event_type", "unknown")
    provider_sub_id = event.get("provider_subscription_id", "")
    custom_id       = event.get("custom_id", "")  # = nuestro sub_id interno

    logger.info(f"[e7/webhook/{provider_key}] {event.get('raw_event_type')} → {event_type}")

    # ── Replay protection — dedup por event_id (Stripe) o PayPal transmission_id ──
    paypal_txn_id = event.get("raw_event_type", "")  # used as fallback key for PayPal
    if provider_key == "paypal":
        # PayPal provides a unique PAYPAL-TRANSMISSION-ID header per delivery
        paypal_event_id = headers.get("paypal-transmission-id", "")
        if paypal_event_id:
            existing = await _db().e7_webhook_events.find_one({"event_id": paypal_event_id})
            if existing:
                logger.debug(f"[e7/webhook] PayPal duplicate ignored: {paypal_event_id}")
                return {"received": True, "duplicate": True, "event_type": event.get("event_type", "unknown")}
            try:
                await _db().e7_webhook_events.insert_one({
                    "event_id":     paypal_event_id,
                    "provider":     "paypal",
                    "event_type":   event.get("event_type", "unknown"),
                    "processed_at": datetime.now(timezone.utc),
                })
            except _DuplicateKeyError:
                logger.debug(f"[e7/webhook] PayPal race duplicate: {paypal_event_id}")
                return {"received": True, "duplicate": True, "event_type": event.get("event_type", "unknown")}

    stripe_event_id = event.get("stripe_event_id", "")
    if stripe_event_id:
        existing = await _db().e7_webhook_events.find_one({"event_id": stripe_event_id})
        if existing:
            logger.debug(f"[e7/webhook] evento duplicado ignorado: {stripe_event_id}")
            return {"received": True, "duplicate": True, "event_type": event_type}
        try:
            await _db().e7_webhook_events.insert_one({
                "event_id":     stripe_event_id,
                "provider":     provider_key,
                "event_type":   event_type,
                "processed_at": datetime.now(timezone.utc),  # datetime (not str) for TTL index
            })
        except _DuplicateKeyError:
            # Two parallel webhook deliveries of the same event; the other won
            logger.debug(f"[e7/webhook] race duplicate ignored: {stripe_event_id}")
            return {"received": True, "duplicate": True, "event_type": event_type}

    # Buscar suscripción interna por custom_id (nuestro sub_id) o provider_sub_id
    sub_doc = None
    if custom_id:
        sub_doc = await _db().e7_subscriptions.find_one({"id": custom_id})
    if not sub_doc and provider_sub_id:
        sub_doc = await _db().e7_subscriptions.find_one(
            {"provider_subscription_id": provider_sub_id}
        )

    if not sub_doc:
        logger.warning(f"[e7/webhook] Suscripción no encontrada: custom_id={custom_id} provider_sub_id={provider_sub_id}")
        await _audit(f"webhook_{event_type}_unmatched", "webhook",
                      {"provider": provider_key, "event": event})
        return {"received": True, "matched": False, "event_type": event_type}

    sub_id = sub_doc["id"]
    tenant_id = sub_doc.get("tenant_id", "")
    now = datetime.now(timezone.utc).isoformat()

    if event_type == "subscription_activated":
        await _db().e7_subscriptions.update_one(
            {"id": sub_id},
            {"$set": {"status": "active", "activated_at": now}}
        )
        await _auto_activate_tenant(
            sub_id, tenant_id, sub_doc.get("plan_key", ""),
            event.get("amount_usd", 0), event.get("currency", "USD"), "webhook"
        )

    elif event_type == "payment_completed":
        await engine_record_payment(
            sub_id, event.get("amount_usd", 0), event.get("currency", "USD"),
            provider_sub_id, provider_key, actor="webhook"
        )
        # Si el tenant estaba suspendido por impago → reactivar
        tenant = await _db().e5_tenants.find_one({"id": tenant_id})
        if tenant and tenant.get("status") == "suspended":
            await _auto_activate_tenant(
                sub_id, tenant_id, sub_doc.get("plan_key", ""),
                event.get("amount_usd", 0), event.get("currency", "USD"), "webhook"
            )

    elif event_type in ("subscription_cancelled", "subscription_expired"):
        await _db().e7_subscriptions.update_one(
            {"id": sub_id},
            {"$set": {"status": event_type.replace("subscription_", ""), "cancelled_at": now},
             "$unset": {"active_slot": ""}}
        )
        # Suspender tenant en E5
        await _db().e5_tenants.update_one(
            {"id": tenant_id},
            {"$set": {"status": "suspended", "suspended_at": now, "updated_at": now}}
        )
        await _audit(f"tenant_suspended_by_{event_type}", "webhook",
                      {"tenant_id": tenant_id, "sub_id": sub_id}, tenant_id)

    elif event_type == "subscription_suspended":
        await _db().e7_subscriptions.update_one({"id": sub_id}, {"$set": {"status": "suspended"}})
        await _db().e5_tenants.update_one(
            {"id": tenant_id},
            {"$set": {"status": "suspended", "suspended_at": now, "updated_at": now}}
        )

    elif event_type == "checkout_session_completed":
        # Actualizar provider_subscription_id con el ID real de suscripción Stripe
        real_sub_id = event.get("provider_subscription_id", "")
        if real_sub_id and real_sub_id.startswith("sub_"):
            await _db().e7_subscriptions.update_one(
                {"id": sub_id},
                {"$set": {"provider_subscription_id": real_sub_id,
                           "status": "active", "activated_at": now}}
            )
        await _auto_activate_tenant(
            sub_id, tenant_id, sub_doc.get("plan_key", ""),
            event.get("amount_usd", 0), event.get("currency", "USD"), "webhook"
        )

    elif event_type == "payment_failed":
        await _db().e7_subscriptions.update_one(
            {"id": sub_id},
            {"$set": {"status": "suspended", "suspended_at": now}}
        )
        await _db().e5_tenants.update_one(
            {"id": tenant_id},
            {"$set": {"status": "suspended", "suspended_at": now, "updated_at": now}}
        )
        await _audit("payment_failed_tenant_suspended", "webhook",
                      {"tenant_id": tenant_id, "sub_id": sub_id,
                       "provider": provider_key}, tenant_id)
        await engine_send_payment_failure_notification(
            sub_id, tenant_id, sub_doc.get("plan_key", ""), actor="webhook"
        )

    elif event_type == "subscription_updated":
        # Sincronizar estado si el provider cambió el status (ej: trial → active)
        if sub_doc:
            await _db().e7_subscriptions.update_one(
                {"id": sub_id},
                {"$set": {"updated_at": now}}
            )

    await _audit(f"webhook_{event_type}", "webhook",
                  {"provider": provider_key, "sub_id": sub_id,
                   "tenant_id": tenant_id, "event": event}, tenant_id)

    return {"received": True, "matched": True, "event_type": event_type,
            "sub_id": sub_id, "tenant_id": tenant_id}


# ─── Refunds ──────────────────────────────────────────────────────────────────

async def engine_refund(sub_id: str, sale_id: str, amount_usd: float,
                         currency: str, reason: str, actor: str) -> dict:
    """
    Emite un reembolso vía el provider de la suscripción.
    sale_id: ID de la transacción en el provider (PayPal sale ID / Stripe charge ID).
    amount_usd=0 → reembolso completo.
    """
    sub_doc = await _db().e7_subscriptions.find_one({"id": sub_id})
    if not sub_doc:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")

    provider_key = sub_doc.get("payment_provider", "paypal")
    tenant_id    = sub_doc.get("tenant_id", "")
    provider     = get_provider(provider_key)

    if not hasattr(provider, "refund_payment"):
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_key}' no soporta refunds directos en este nivel"
        )

    result = await provider.refund_payment(sale_id, amount_usd, currency, reason)

    ref_id = "ref_" + secrets.token_urlsafe(10)
    doc = {
        "id": ref_id,
        "sub_id": sub_id,
        "tenant_id": tenant_id,
        "payment_provider": provider_key,
        "sale_id": sale_id,
        "refund_id": result.get("refund_id", ""),
        "amount_usd": result.get("amount_usd", amount_usd),
        "currency": currency,
        "reason": reason,
        "status": result.get("status", "completed"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": actor,
    }
    await _db().e7_refunds.insert_one(doc)
    await _audit("refund_issued", actor,
                  {"ref_id": ref_id, "sub_id": sub_id, "amount_usd": doc["amount_usd"],
                   "sale_id": sale_id}, tenant_id)
    return {k: v for k, v in doc.items() if k != "_id"}


async def engine_send_payment_failure_notification(sub_id: str, tenant_id: str,
                                                    plan_key: str, actor: str = "webhook") -> None:
    """
    Emite evento E9 + encola email de notificación de pago fallido.
    No lanza excepción si falla — el sistema ya suspendió el tenant.
    """
    try:
        from e9_emitters import track_call as _track
        # Email via E4 si está disponible
        try:
            import e4_email
            sub_doc = await _db().e7_subscriptions.find_one({"id": sub_id})
            billing_email = (sub_doc or {}).get("billing_email", "")
            if billing_email and e4_email._db() is not None:
                plan_info = BILLING_PLANS.get(plan_key, {})
                await e4_email.send_email(
                    tenant_id=tenant_id,
                    to_email=billing_email,
                    subject="Pago fallido — acción requerida",
                    html_body=(
                        f"<p>Tu pago para el plan <strong>{plan_info.get('name', plan_key)}</strong> "
                        f"no pudo procesarse.</p>"
                        f"<p>Tu cuenta ha sido suspendida temporalmente. "
                        f"Por favor actualiza tu método de pago para reactivarla.</p>"
                        f"<p>Si crees que es un error, contáctanos.</p>"
                    ),
                    include_unsub=False,
                    idempotency_key=f"payment_fail_{sub_id}",
                )
        except Exception as email_exc:
            logger.warning(f"[e7] payment failure email failed: {email_exc}")

        await _audit("payment_failure_notification_sent", actor,
                      {"sub_id": sub_id, "tenant_id": tenant_id}, tenant_id)
    except Exception as exc:
        logger.error(f"[e7] payment failure notification failed: {exc}")


# ─── Indexes ──────────────────────────────────────────────────────────────────

async def create_indexes() -> None:
    db = _db()
    await db.e7_subscriptions.create_index("id", unique=True)
    await db.e7_subscriptions.create_index([("tenant_id", 1), ("status", 1)])
    await db.e7_subscriptions.create_index("provider_subscription_id", sparse=True)
    # Unique sparse: exactly one active/pending subscription per tenant.
    # active_slot="1" is set on insert, $unset on cancel/expire.
    await db.e7_subscriptions.create_index(
        [("tenant_id", 1), ("active_slot", 1)],
        unique=True, sparse=True,
        name="idx_e7_active_slot_per_tenant"
    )
    await db.e7_payments.create_index([("sub_id", 1), ("received_at", -1)])
    await db.e7_billing_plans.create_index(
        [("plan_key", 1), ("provider", 1)], unique=True, sparse=True
    )
    await db.e7_webhook_events.create_index("event_id", unique=True)
    await db.e7_webhook_events.create_index(
        "processed_at", expireAfterSeconds=86400 * 30
    )
    await db.e7_refunds.create_index([("sub_id", 1), ("created_at", -1)])
    await db.e7_refunds.create_index([("tenant_id", 1), ("status", 1)])
    logger.info("[e7] Indexes OK")


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — callable por E1 vía call_specialist_tool
# ═══════════════════════════════════════════════════════════════════════════════

async def tool_stripe_manager(action: str, tenant_id: str = "", params: dict = None) -> dict:
    """Compatibilidad con nombre anterior. Ahora delega a provider_manager."""
    return await tool_billing_control(action, tenant_id)


@track_call(module="e7_billing", event_prefix="e7.subscription_engine")
async def tool_subscription_engine(tenant_id: str, plan_key: str,
                                    action: str = "create",
                                    billing_email: str = "",
                                    payment_provider: str = "paypal") -> dict:
    if action == "create":
        return await engine_subscribe(tenant_id, plan_key, payment_provider,
                                       billing_email, actor="e1_tool")
    if action == "cancel":
        sub = await _db().e7_subscriptions.find_one(
            {"tenant_id": tenant_id, "status": "active"}, {"id": 1}
        )
        if not sub:
            return {"error": "No hay suscripción activa para este tenant"}
        return await engine_cancel(sub["id"], "Cancelado vía E1", "e1_tool")
    if action == "summary":
        return await engine_billing_summary(tenant_id)
    if action == "status" and tenant_id:
        sub = await _db().e7_subscriptions.find_one(
            {"tenant_id": tenant_id}, {"_id": 0}
        )
        if not sub:
            return {"tenant_id": tenant_id, "subscription": None}
        provider = get_provider(sub["payment_provider"])
        if sub.get("provider_subscription_id"):
            live = await provider.get_subscription_status(sub["provider_subscription_id"])
            sub["live_status"] = live
        return sub
    raise ValueError(f"action desconocida: {action}")


@track_call(module="e7_billing", event_prefix="e7.invoice_generator")
async def tool_invoice_generator(tenant_id: str, items: list,
                                  billing_email: str = "",
                                  due_days: int = 15,
                                  currency: str = "USD") -> dict:
    return await engine_generate_invoice(tenant_id, items, billing_email,
                                          due_days, currency, actor="e1_tool")


@track_call(module="e7_billing", event_prefix="e7.usage_meter")
async def tool_usage_meter(tenant_id: str, metric: str, value: float,
                            period: str = "") -> dict:
    return await engine_track_usage(tenant_id, metric, value, period)


async def tool_billing_control(action: str, tenant_id: str = "") -> dict:
    if action == "summary" and tenant_id:
        return await engine_billing_summary(tenant_id)
    if action == "plans":
        return {"plans": BILLING_PLANS, "providers": PROVIDERS}
    if action == "usage" and tenant_id:
        cur = _db().e7_usage.find({"tenant_id": tenant_id}, {"_id": 0})
        return {"usage": [u async for u in cur]}
    raise ValueError(f"action desconocida o tenant_id faltante: {action}")


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class SubscribeIn(BaseModel):
    tenant_id: str
    plan_key: str
    payment_provider: str = Field("paypal", description="paypal|stripe|manual")
    billing_email: str = ""


class InvoiceIn(BaseModel):
    tenant_id: str
    items: List[dict]
    billing_email: str = ""
    due_days: int = 15
    currency: str = "USD"


class UsageIn(BaseModel):
    tenant_id: str
    metric: str
    value: float
    period: Optional[str] = None


@router.get("/plans")
async def list_plans():
    """Lista planes disponibles con precios."""
    return {"plans": BILLING_PLANS, "providers": PROVIDERS}


@router.post("/subscriptions")
async def create_subscription(data: SubscribeIn, user: dict = Depends(auth.get_current_user)):
    """
    Crea suscripción recurrente.
    PayPal: retorna approval_url para redirigir al usuario.
    Manual: activa inmediatamente (sin pago).
    """
    return await engine_subscribe(
        data.tenant_id, data.plan_key, data.payment_provider,
        data.billing_email, actor=user["email"]
    )


@router.get("/subscriptions/{tenant_id}")
async def get_subscription(tenant_id: str, user: dict = Depends(auth.get_current_user)):
    sub = await _db().e7_subscriptions.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if not sub:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    return sub


@router.get("/subscriptions/{tenant_id}/status-live")
async def get_subscription_live_status(tenant_id: str,
                                        user: dict = Depends(auth.get_current_user)):
    """Consulta estado en tiempo real directamente al provider."""
    sub = await _db().e7_subscriptions.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if not sub or not sub.get("provider_subscription_id"):
        raise HTTPException(status_code=404, detail="Sin suscripción activa con provider")
    provider = get_provider(sub["payment_provider"])
    live = await provider.get_subscription_status(sub["provider_subscription_id"])
    return {"local": sub, "live": live}


@router.post("/subscriptions/{sub_id}/cancel")
async def cancel_subscription(sub_id: str, reason: str = "",
                               user: dict = Depends(auth.get_current_user)):
    return await engine_cancel(sub_id, reason, actor=user["email"])


@router.get("/subscriptions")
async def list_subscriptions(user: dict = Depends(auth.get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")
    cur = _db().e7_subscriptions.find({}, {"_id": 0}).sort("created_at", -1).limit(200)
    return {"subscriptions": [s async for s in cur]}


@router.post("/invoices")
async def create_invoice(data: InvoiceIn, user: dict = Depends(auth.get_current_user)):
    return await engine_generate_invoice(
        data.tenant_id, data.items, data.billing_email,
        data.due_days, data.currency, actor=user["email"]
    )


@router.get("/invoices")
async def list_invoices(tenant_id: Optional[str] = None,
                         user: dict = Depends(auth.get_current_user)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e7_invoices.find(q, {"_id": 0}).sort("created_at", -1).limit(50)
    return {"invoices": [i async for i in cur]}


@router.post("/usage")
async def record_usage(data: UsageIn, user: dict = Depends(auth.get_current_user)):
    return await engine_track_usage(data.tenant_id, data.metric, data.value, data.period or "")


@router.get("/usage/{tenant_id}")
async def get_usage(tenant_id: str, period: Optional[str] = None,
                     user: dict = Depends(auth.get_current_user)):
    q: dict = {"tenant_id": tenant_id}
    if period:
        q["period"] = period
    cur = _db().e7_usage.find(q, {"_id": 0})
    return {"usage": [u async for u in cur]}


@router.get("/summary/{tenant_id}")
async def billing_summary(tenant_id: str, user: dict = Depends(auth.get_current_user)):
    return await engine_billing_summary(tenant_id)


# ─── Webhooks ─────────────────────────────────────────────────────────────────

@router.post("/webhook/paypal")
async def paypal_webhook(request: Request):
    """
    Webhook PayPal — valida firma via PAYPAL_WEBHOOK_ID (ya configurado).
    Eventos: BILLING.SUBSCRIPTION.ACTIVATED, PAYMENT.SALE.COMPLETED,
             BILLING.SUBSCRIPTION.CANCELLED, BILLING.SUBSCRIPTION.SUSPENDED.
    """
    body = await request.body()
    return await handle_provider_webhook("paypal", dict(request.headers), body)


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Webhook Stripe — Phase 2. Activo cuando STRIPE_SECRET_KEY esté configurado."""
    body = await request.body()
    return await handle_provider_webhook("stripe", dict(request.headers), body)


class RefundIn(BaseModel):
    sub_id: str
    sale_id: str
    amount_usd: float = Field(0.0, description="0 = reembolso completo")
    currency: str = "USD"
    reason: str = ""


@router.post("/refunds")
async def create_refund(data: RefundIn, user: dict = Depends(auth.require_admin)):
    """Emite un reembolso vía el provider de la suscripción."""
    return await engine_refund(
        data.sub_id, data.sale_id, data.amount_usd,
        data.currency, data.reason, actor=user["email"]
    )


@router.get("/refunds")
async def list_refunds(tenant_id: Optional[str] = None,
                        user: dict = Depends(auth.require_admin)):
    q = {"tenant_id": tenant_id} if tenant_id else {}
    cur = _db().e7_refunds.find(q, {"_id": 0}).sort("created_at", -1).limit(100)
    return {"refunds": [r async for r in cur]}


@router.get("/providers")
async def list_providers():
    """Lista providers disponibles y su estado de configuración."""
    return {
        "providers": {
            "paypal": {
                "configured": bool(os.getenv("PAYPAL_CLIENT_ID")),
                "mode": os.getenv("PAYPAL_MODE", "live"),
                "phase": 1,
                "status": "active",
            },
            "stripe": {
                "configured": bool(os.getenv("STRIPE_SECRET_KEY")),
                "phase": 2,
                "status": "prep — configurar STRIPE_SECRET_KEY para activar",
            },
            "manual": {
                "configured": True,
                "phase": 1,
                "status": "active — activación enterprise sin pago",
            },
        }
    }
