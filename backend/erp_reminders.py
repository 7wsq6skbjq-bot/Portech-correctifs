"""
Automatic invoice reminders — 2 paliers (J+7 amical, J+30 ferme).

The scheduler runs daily at 08:00 America/Montreal and emails a reminder to
any invoice whose `due_date` is 7 or 30 days past *and* whose `status` is
'envoyée' (never to drafts or paid/cancelled invoices).

Idempotency is enforced by the `reminder_level_sent` field on each invoice
(values: 0, 7, 30). We only send a reminder for a level that hasn't been
sent yet. A manual admin endpoint `POST /admin/invoices/{id}/send-reminder`
is also exposed for testing or overrides.
"""
import asyncio
import logging
from datetime import date, datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Body, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from erp_automations import automation_active
from erp_helpers import send_pdf_email
from erp_pdf import render_invoice_pdf
from erp_models import EmailSendRequest  # noqa: F401 — re-exported for callers

logger = logging.getLogger("portech.erp.reminders")


async def reminders_paused(db: AsyncIOMotorDatabase) -> bool:
    """Vrai si les relances automatiques ne doivent PAS partir. Réglable dans
    l'ERP (Factures → Envois automatiques) ; ACTIVÉES PAR DÉFAUT.
    ERP_REMINDERS_PAUSED=true reste un interrupteur d'urgence côté serveur."""
    return not await automation_active(db, "invoice_reminders")

# Deux paliers. Escalade STRICTE : l'amical (7) est TOUJOURS envoyé en premier ;
# le ferme (30) n'est émis qu'APRÈS l'amical et après un délai minimum.
PALIERS = [
    {"level": 7, "threshold": 7, "tone": "friendly"},
    {"level": 30, "threshold": 30, "tone": "firm"},
]

# Statuts relançables (jamais payée / annulée / brouillon / en attente).
REMINDABLE_STATUSES = ["envoyée", "en retard", "partiellement payée"]

# Délai minimum (jours) entre le rappel amical (J+7) et le rappel ferme (J+30).
MIN_DAYS_BETWEEN_PALIERS = 7


def _days_past_due(due_date_iso: str | None, today: date) -> int | None:
    if not due_date_iso:
        return None
    try:
        due = datetime.strptime(due_date_iso[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (today - due).days


def _days_since(iso: str | None, today: date) -> int | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            d = datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return (today - d).days


def _reminder_target(days: int, already: int, last_sent_iso: str | None,
                     today: date) -> int | None:
    """Palier à envoyer en respectant l'escalade stricte amical → ferme.
    - amical (7) TOUJOURS en premier dès 7 jours de retard ;
    - ferme (30) uniquement si l'amical est déjà parti (already >= 7), que le
      retard atteint 30 jours ET qu'un délai minimum s'est écoulé depuis le
      dernier rappel."""
    if days < 7:
        return None
    if already < 7:
        return 7
    if already < 30 and days >= 30:
        gap = _days_since(last_sent_iso, today)
        if gap is None or gap >= MIN_DAYS_BETWEEN_PALIERS:
            return 30
    return None


async def _invoice_balance(db, invoice_id: str, total: float) -> tuple[float, float, float]:
    """Retourne (paiements, notes de crédit, solde dû) — lecture seule."""
    paid = 0.0
    async for p in db.erp_payments.find({"invoice_id": invoice_id}, {"amount": 1}):
        paid += float(p.get("amount", 0) or 0)
    credited = 0.0
    async for c in db.erp_credit_notes.find({"invoice_id": invoice_id}, {"amount": 1}):
        credited += float(c.get("amount", 0) or 0)
    return round(paid, 2), round(credited, 2), round(total - paid - credited, 2)


def _friendly_message(invoice: dict, number: str, days: int, balance: float) -> tuple[str, str]:
    cust = (invoice.get("customer_snapshot") or {}).get("name") or "Bonjour"
    subject = f"Rappel — Facture {number} échue depuis {days} jour{'s' if days > 1 else ''}"
    html = (
        f"<p>Bonjour {cust},</p>"
        f"<p>Un petit rappel amical : la facture <b>{number}</b> présente un "
        f"solde dû de <b>{balance:.2f} $ CAD</b>, échu depuis {days} jour"
        f"{'s' if days > 1 else ''}.</p>"
        "<p>Vous trouverez en pièce jointe une copie de la facture. "
        "Si le paiement a déjà été effectué, merci d'ignorer ce courriel.</p>"
        "<p>Pour toute question, répondez simplement à ce message.</p>"
        "<p>Cordialement,</p>"
    )
    return subject, html


def _firm_message(invoice: dict, number: str, days: int, balance: float) -> tuple[str, str]:
    cust = (invoice.get("customer_snapshot") or {}).get("name") or "Bonjour"
    subject = f"[Important] Facture {number} — {days} jours de retard"
    html = (
        f"<p>Bonjour {cust},</p>"
        f"<p>Malgré notre précédent rappel, la facture <b>{number}</b> présente "
        f"toujours un solde dû de <b>{balance:.2f} $ CAD</b>, impayé depuis "
        f"<b>{days} jours</b>.</p>"
        "<p>Modalités de paiement · Net 30 jours. Intérêts de 1,5 % par mois "
        "sur les soldes en souffrance.</p>"
        "<p>Merci de régulariser la situation dans les meilleurs délais, "
        "ou de nous contacter pour convenir d'un arrangement.</p>"
        "<p>Cordialement,</p>"
    )
    return subject, html


async def send_reminder_for_invoice(
    db: AsyncIOMotorDatabase, invoice: dict, level: int, *, atomic: bool = True,
) -> bool:
    """Send a reminder email for a specific invoice at the given palier level.
    Returns True on success, False otherwise.

    When `atomic` is True (scheduler path), the palier is RESERVED atomically
    *before* sending: `find_one_and_update` bumps `reminder_level_sent` to the
    target level only if the invoice is still 'envoyée' and hasn't already
    reached that level. This makes the daily run idempotent and safe even with
    several instances running in parallel — only one wins the reservation and
    sends. On email failure the reservation is rolled back.

    When `atomic` is False (manual override endpoint), the email is always sent
    and the fields are simply updated afterwards.
    """
    to_email = (invoice.get("customer_snapshot") or {}).get("email")
    if not to_email:
        logger.warning("Skip reminder for %s — no customer email", invoice.get("id"))
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    prev_level = int(invoice.get("reminder_level_sent", 0) or 0)
    if atomic:
        # Réservation atomique respectant l'escalade stricte :
        #  - niveau 7 : seulement si aucun rappel encore (reminder_level_sent < 7) ;
        #  - niveau 30 : seulement si l'amical est déjà parti (>= 7) et < 30.
        lvl_filter = {"$lt": 7} if level == 7 else {"$gte": 7, "$lt": 30}
        reserved = await db.erp_invoices.find_one_and_update(
            {"id": invoice["id"], "status": {"$in": REMINDABLE_STATUSES},
             "reminder_level_sent": lvl_filter},
            {"$set": {"reminder_level_sent": level,
                      "last_reminder_sent_at": now_iso}},
            projection={"_id": 0},
        )
        if not reserved:
            # Déjà envoyé, statut non relançable, ou escalade non respectée.
            return False
        prev_level = int(reserved.get("reminder_level_sent", 0) or 0)

    number = f"FAC-{int(invoice['number']):04d}"
    d = _days_past_due(invoice.get("due_date"), date.today())
    days = d if (d is not None and d >= 0) else 0
    _, _, balance = await _invoice_balance(
        db, invoice["id"], float(invoice.get("total", 0) or 0))
    if level == 7:
        subject, html = _friendly_message(invoice, number, days, balance)
    else:
        subject, html = _firm_message(invoice, number, days, balance)

    pdf_bytes = await asyncio.to_thread(render_invoice_pdf, invoice)
    try:
        await send_pdf_email(
            to_email=to_email, subject=subject, html=html,
            pdf_bytes=pdf_bytes, filename=f"{number}.pdf",
            email_type="relance",
            linked_document={"kind": "invoice", "id": invoice["id"],
                             "number": invoice.get("number"), "label": number,
                             "customer": (invoice.get("customer_snapshot") or {}).get("name")},
            trigger="scheduler" if atomic else "user",
        )
    except HTTPException as exc:
        logger.error("Reminder email failed for %s: %s", number, exc.detail)
        if atomic:
            # Libère la réservation pour un prochain essai.
            await db.erp_invoices.update_one(
                {"id": invoice["id"]},
                {"$set": {"reminder_level_sent": prev_level}})
        return False

    if not atomic:
        await db.erp_invoices.update_one(
            {"id": invoice["id"]},
            {"$set": {"reminder_level_sent": level,
                      "last_reminder_sent_at": now_iso}},
        )
    logger.info("Reminder sent %s level=%d", number, level)
    return True


async def run_daily_reminders(db: AsyncIOMotorDatabase) -> dict:
    """Scan all 'envoyée' invoices and send reminders for any that are due.
    Idempotent: only sends a palier that hasn't been sent yet for that invoice.
    """
    today = date.today()
    cursor = db.erp_invoices.find({"status": {"$in": REMINDABLE_STATUSES}}, {"_id": 0})
    sent_count = 0
    skipped_count = 0
    async for inv in cursor:
        days = _days_past_due(inv.get("due_date"), today)
        if days is None or days < 7:
            continue
        # Ne relance que s'il reste un solde dû.
        _, _, balance = await _invoice_balance(
            db, inv["id"], float(inv.get("total", 0) or 0))
        if balance <= 0.005:
            continue
        already_sent = int(inv.get("reminder_level_sent", 0) or 0)
        target = _reminder_target(days, already_sent,
                                  inv.get("last_reminder_sent_at"), today)
        if target is None:
            skipped_count += 1
            continue
        ok = await send_reminder_for_invoice(db, inv, target)
        if ok:
            sent_count += 1
    logger.info("Daily reminder run: sent=%d skipped=%d", sent_count, skipped_count)
    return {"sent": sent_count, "skipped": skipped_count, "date": today.isoformat()}


def start_scheduler(db: AsyncIOMotorDatabase) -> AsyncIOScheduler:
    """Create and start the APScheduler that runs `run_daily_reminders` each
    morning at 08:00 America/Montreal. Returns the scheduler instance so the
    caller can shut it down cleanly on app shutdown."""

    async def _scheduled_run():
        # Garde-fou : les relances AUTOMATIQUES peuvent être suspendues
        # (ERP_REMINDERS_PAUSED) sans toucher au déclenchement manuel.
        if await reminders_paused(db):
            logger.warning("Relances automatiques SUSPENDUES "
                           "(réglage ERP ou ERP_REMINDERS_PAUSED) — tâche quotidienne ignorée.")
            return {"sent": 0, "skipped": 0, "paused": True,
                    "date": date.today().isoformat()}
        return await run_daily_reminders(db)

    sched = AsyncIOScheduler(timezone="America/Montreal")
    sched.add_job(
        _scheduled_run, "cron",
        hour=8, minute=0,
        id="erp_daily_reminders",
        replace_existing=True,
    )
    sched.start()
    logger.info("Invoice reminder scheduler started (daily 08:00 America/Montreal)")
    return sched


def register_routes(router: APIRouter, db: AsyncIOMotorDatabase, auth_dep) -> None:
    """Expose admin endpoints for manual triggering + status introspection."""

    @router.post("/invoices/{invoice_id}/send-reminder")
    async def send_reminder_manual(
        invoice_id: str,
        level: int = 7,
        _: dict = Depends(auth_dep),
    ):
        if level not in (7, 30):
            raise HTTPException(400, "Palier invalide (7 ou 30 seulement)")
        inv = await db.erp_invoices.find_one({"id": invoice_id}, {"_id": 0})
        if not inv:
            raise HTTPException(404, "Facture introuvable")
        if not (inv.get("customer_snapshot") or {}).get("email"):
            raise HTTPException(400, "Aucun courriel client sur cette facture")
        ok = await send_reminder_for_invoice(db, inv, level, atomic=False)
        if not ok:
            raise HTTPException(502, "Échec de l'envoi")
        return {"sent": True, "level": level, "invoice_id": invoice_id}

    @router.post("/reminders/run-now")
    async def run_reminders_now(body: dict = Body(default={}),
                                _: dict = Depends(auth_dep)):
        """Déclenche manuellement le balayage complet des relances.
        Refusé si les relances sont suspendues (ne contourne plus la pause) et
        exige une confirmation explicite du propriétaire."""
        if await reminders_paused(db):
            raise HTTPException(403, "Relances désactivées — exécution refusée. "
                                "Réactivez-les d'abord dans Factures → Envois automatiques.")
        if (body or {}).get("confirm") != "EXECUTER":
            raise HTTPException(400, 'Confirmation requise : {"confirm":"EXECUTER"}')
        return await run_daily_reminders(db)

    @router.get("/reminders/preview")
    async def reminders_preview(_: dict = Depends(auth_dep)):
        """LECTURE SEULE : factures qui seraient relancées au prochain run 08:00.
        N'envoie aucun courriel et ne modifie rien. Applique EXACTEMENT la même
        logique que la tâche quotidienne (statuts relançables, solde dû > 0,
        escalade stricte amical → ferme). Les factures payées / annulées /
        brouillons / en attente sont exclues."""
        today = date.today()
        items = []
        async for inv in db.erp_invoices.find({"status": {"$in": REMINDABLE_STATUSES}}, {"_id": 0}):
            days = _days_past_due(inv.get("due_date"), today)
            if days is None or days < 7:
                continue
            total = float(inv.get("total", 0) or 0)
            paid, credited, balance = await _invoice_balance(db, inv["id"], total)
            if balance <= 0.005:
                continue
            already = int(inv.get("reminder_level_sent", 0) or 0)
            target = _reminder_target(days, already,
                                      inv.get("last_reminder_sent_at"), today)
            if target is None:
                continue
            snap = inv.get("customer_snapshot") or {}
            items.append({
                "number": f"FAC-{int(inv['number']):04d}",
                "status": inv.get("status"),
                "customer": snap.get("name"),
                "email": snap.get("email"),
                "has_email": bool(snap.get("email")),
                "due_date": inv.get("due_date"),
                "days_past_due": days,
                "already_sent_level": already,
                "last_reminder_sent_at": inv.get("last_reminder_sent_at"),
                "target_level": target,
                "palier": "amical (J+7)" if target == 7 else "ferme (J+30)",
                "total": round(total, 2),
                "paid_total": paid,
                "credit_total": credited,
                "balance": balance,
            })
        items.sort(key=lambda x: -x["days_past_due"])
        return {"as_of": today.isoformat(), "count": len(items), "invoices": items}
