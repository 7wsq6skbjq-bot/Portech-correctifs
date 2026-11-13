"""Interrupteurs des envois automatiques de l'ERP (relances, relevés, suivis).

Avant : chaque automatisme dépendait d'une variable d'environnement et était
SUSPENDU PAR DÉFAUT — il fallait modifier la configuration du serveur puis
redéployer pour l'activer, et rien dans l'ERP n'indiquait qu'il était éteint.

Maintenant : chaque automatisme a un interrupteur visible et modifiable dans
l'ERP (stocké dans `erp_settings`, clé `automations`). Les variables
d'environnement restent des interrupteurs d'urgence côté serveur :
  - ERP_REMINDERS_PAUSED=true  → force l'arrêt des relances de factures ;
  - ERP_MONTHLY_STATEMENTS=true / ERP_QUOTE_FOLLOWUPS=true → forcent l'activation
    (compatibilité avec l'ancienne configuration).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger("portech.erp.automations")

SETTINGS_KEY = "automations"

# clé → (libellé, description, valeur par défaut)
AUTOMATIONS = {
    "invoice_reminders": (
        "Relances de factures en retard",
        "Courriel automatique au client à J+7 (amical) puis J+30 (ferme), "
        "tous les jours à 8 h, avec la facture en pièce jointe.",
        True,
    ),
    "monthly_statements": (
        "États de compte mensuels",
        "Le 1er de chaque mois à 9 h, envoie à chaque client qui a un solde dû "
        "son état de compte en PDF.",
        False,
    ),
    "quote_followups": (
        "Suivi des soumissions sans réponse",
        "Tous les jours à 8 h 30, un seul courriel de suivi poli pour chaque "
        "soumission envoyée restée sans réponse.",
        False,
    ),
}

_ENV_FORCE_ON = {
    "monthly_statements": "ERP_MONTHLY_STATEMENTS",
    "quote_followups": "ERP_QUOTE_FOLLOWUPS",
}
_ENV_FORCE_OFF = {
    "invoice_reminders": "ERP_REMINDERS_PAUSED",
}


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _stored(db: AsyncIOMotorDatabase) -> dict:
    doc = await db.erp_settings.find_one({"key": SETTINGS_KEY}, {"_id": 0}) or {}
    return doc.get("values") or {}


async def automation_state(db: AsyncIOMotorDatabase, key: str) -> dict:
    label, desc, default = AUTOMATIONS[key]
    stored = await _stored(db)
    enabled = bool(stored.get(key, default))
    forced_off = key in _ENV_FORCE_OFF and _env_true(_ENV_FORCE_OFF[key])
    forced_on = key in _ENV_FORCE_ON and _env_true(_ENV_FORCE_ON[key])
    active = (enabled or forced_on) and not forced_off
    note = None
    if forced_off:
        note = f"Bloqué côté serveur ({_ENV_FORCE_OFF[key]}=true)."
    elif forced_on and not enabled:
        note = f"Forcé côté serveur ({_ENV_FORCE_ON[key]}=true)."
    return {"key": key, "label": label, "description": desc,
            "enabled": enabled, "active": active, "server_note": note}


async def automation_active(db: AsyncIOMotorDatabase, key: str) -> bool:
    return (await automation_state(db, key))["active"]


def register(router: APIRouter, db: AsyncIOMotorDatabase, auth_dep) -> None:

    @router.get("/automations")
    async def list_automations(_: dict = Depends(auth_dep)):
        return {"automations": [await automation_state(db, k) for k in AUTOMATIONS]}

    @router.put("/automations/{key}")
    async def set_automation(key: str, body: dict = Body(...), current=Depends(auth_dep)):
        if key not in AUTOMATIONS:
            raise HTTPException(404, "Automatisme inconnu.")
        if "enabled" not in (body or {}):
            raise HTTPException(400, "Champ « enabled » requis (true/false).")
        enabled = bool(body["enabled"])
        await db.erp_settings.update_one(
            {"key": SETTINGS_KEY},
            {"$set": {"key": SETTINGS_KEY, f"values.{key}": enabled,
                      "updated_at": datetime.now(timezone.utc).isoformat(),
                      "updated_by": getattr(current, "username", None)}},
            upsert=True,
        )
        logger.info("Automatisme %s → %s (par %s)", key,
                    "ACTIVÉ" if enabled else "DÉSACTIVÉ", getattr(current, "username", "?"))
        return await automation_state(db, key)
