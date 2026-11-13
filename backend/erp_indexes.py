"""Index MongoDB pour toutes les collections erp_* (Phase 2A).

`ensure_erp_indexes(db)` est idempotent et non destructif : chaque index est
créé indépendamment dans un try/except, de sorte qu'une collection comportant
des doublons historiques (qui empêcheraient un index unique) ne bloque jamais
le démarrage — l'échec est journalisé et les autres index sont tout de même
posés. Aucune donnée n'est supprimée ni modifiée.

Couverture demandée : identifiant unique, numéro unique (par collection),
statut, date.
"""
import logging

from pymongo import ASCENDING

logger = logging.getLogger("portech.erp.indexes")

# field name of the sequential document number, per collection
_NUMBER_FIELD = {
    "erp_invoices": "number",
    "erp_quotes": "number",
    "erp_purchase_orders": "number",
    "erp_bills_of_lading": "number",
    "erp_expert_reports": "number",
    "erp_production_plans": "plan_number",
    "erp_payment_notices": "notice_number",
    "erp_mosquito_screens": "order_number",
    "erp_work_orders": "number",
}

# collections that carry a `status` field worth indexing
_HAS_STATUS = {
    "erp_invoices", "erp_quotes", "erp_purchase_orders",
    "erp_bills_of_lading", "erp_expert_reports", "erp_work_orders",
}

# collections that carry a `date` field worth indexing
_HAS_DATE = {
    "erp_invoices", "erp_quotes", "erp_purchase_orders",
    "erp_bills_of_lading", "erp_expert_reports",
    "erp_expenses", "erp_mileage",
}

# every document collection keyed by the app-level `id` (uuid or int)
_HAS_ID = set(_NUMBER_FIELD) | {
    "erp_expenses", "erp_mileage", "erp_parties", "erp_products", "erp_jobs",
    "erp_payments", "erp_credit_notes", "erp_audit",
}

# extra single-field indexes (non unique)
_EXTRA = {
    "erp_jobs": [("stage", ASCENDING)],
    "erp_parties": [("kind", ASCENDING)],
    "erp_products": [("sku", ASCENDING)],
    "erp_expenses": [("category", ASCENDING)],
    "erp_payments": [("invoice_id", ASCENDING)],
    "erp_credit_notes": [("invoice_id", ASCENDING)],
    "erp_audit": [("entity", ASCENDING), ("entity_id", ASCENDING), ("at", ASCENDING)],
}


async def _safe_create(coll, keys, **opts) -> None:
    try:
        await coll.create_index(keys, **opts)
    except Exception as exc:  # DuplicateKey on legacy dupes, option clash, etc.
        logger.warning("Index %s sur %s ignoré : %s", opts.get("name") or keys,
                       coll.name, exc)


async def ensure_erp_indexes(db) -> None:
    """Create all erp_* indexes. Idempotent, safe to run on every boot."""
    collections = (
        set(_NUMBER_FIELD) | _HAS_STATUS | _HAS_DATE | _HAS_ID | set(_EXTRA)
    )
    for name in sorted(collections):
        coll = db[name]
        if name in _HAS_ID:
            await _safe_create(
                coll, [("id", ASCENDING)], unique=True, name="uq_id",
                partialFilterExpression={"id": {"$exists": True}})
        num_field = _NUMBER_FIELD.get(name)
        if num_field:
            await _safe_create(
                coll, [(num_field, ASCENDING)], unique=True,
                name=f"uq_{num_field}",
                partialFilterExpression={num_field: {"$exists": True}})
        if name in _HAS_STATUS:
            await _safe_create(coll, [("status", ASCENDING)], name="ix_status")
        if name in _HAS_DATE:
            await _safe_create(coll, [("date", ASCENDING)], name="ix_date")
        for keys in _EXTRA.get(name, []):
            await _safe_create(coll, [keys], name=f"ix_{keys[0]}")
    # Échecs de connexion : effacés automatiquement après 1 h ; recherche par IP / identifiant.
    await _safe_create(db.auth_login_failures, [("at", ASCENDING)],
                       name="ttl_at", expireAfterSeconds=3600)
    await _safe_create(db.auth_login_failures, [("ip", ASCENDING), ("at", ASCENDING)], name="ix_ip_at")
    await _safe_create(db.auth_login_failures, [("username", ASCENDING), ("at", ASCENDING)], name="ix_user_at")
    logger.info("Index erp_* assurés (%d collections)", len(collections))
