"""Shared helpers for the Portech ERP: tax math, counters, CSV, email, date parse."""
import base64
import csv
import html as _html_mod
import io
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import resend
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from erp_models import LineItem, TPS_RATE, TVQ_RATE

logger = logging.getLogger("portech.erp")

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")

# Inbox that actually RECEIVES replies. The portech.info domain has no MX
# records (Resend is send-only) so a client clicking "Reply" on info@portech.info
# would bounce into the void — that's exactly the bug Cédrick reported (clients
# replying to POs/invoices and Cédrick never seeing it). We mirror the same
# default the prospection routes already use so replies all land in one inbox.
REPLY_TO_EMAIL = os.environ.get(
    "ERP_REPLY_TO_EMAIL",
    os.environ.get("LEADS_RECIPIENT_EMAIL", "portech.infos@gmail.com"),
)


# Matches any HTML tag the user might have typed deliberately ; if present we
# assume the caller already provided ready-to-send HTML and leave it alone.
_HTML_TAG_RE = re.compile(r"<\s*(p|br|div|table|ul|ol|li|h[1-6]|strong|em|b|i|a|img|hr)\b",
                          re.IGNORECASE)


def normalize_message_to_html(msg: str) -> str:
    """Convert a user-typed message into safe HTML preserving whitespace.

    The ERP UI (PO, BOL, invoice, supplier emails) is a plain `<textarea>` —
    when Cédrick presses Enter twice to make a blank line between paragraphs,
    those newlines must reach the recipient. Without conversion the HTML
    renderer collapses them and the supplier sees a wall of text.

    Behaviour :
      * If the input already contains an HTML tag (the route default messages
        are written in HTML) → return as-is. No double-escaping.
      * Otherwise : escape HTML entities, split on blank lines into <p>s,
        and convert remaining single newlines to <br/>. Preserve runs of
        spaces with &nbsp; chains so indentation doesn't collapse.
    """
    if not msg:
        return ""
    if _HTML_TAG_RE.search(msg):
        return msg
    # 1. Escape so the user can safely type <, > or & without breaking HTML.
    safe = _html_mod.escape(msg, quote=False)
    # 2. Preserve runs of >1 spaces (Outlook/Gmail collapse them otherwise).
    safe = re.sub(r" {2,}", lambda m: "&nbsp;" * len(m.group(0)), safe)
    # 3. Normalize newlines, split on blank line(s) → paragraphs.
    safe = safe.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n\s*\n", safe.strip("\n"))
    out_parts: list[str] = []
    for p in paragraphs:
        # Within a paragraph, single \n → <br/>
        p_html = p.replace("\n", "<br/>")
        out_parts.append(f'<p style="margin:0 0 12px 0;">{p_html}</p>')
    return "".join(out_parts)


# ---------- Branded email wrapper (matches prospection campaigns) ----------
# Banners are inline-attached (CID) so recipients always see them, even if the
# portech.info domain is unreachable or blocked by a corporate mail gateway.
# Files live inside the backend folder so they ship with the backend container.
_BANNER_DIR = Path(__file__).parent / "email_assets"
HEADER_CID = "portech-header.png"
FOOTER_CID = "portech-footer.png"


def _load_banner_b64(filename: str) -> Optional[str]:
    p = _BANNER_DIR / filename
    if not p.exists():
        logger.warning("Banner file not found: %s", p)
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")


_BANNER_HEADER_B64 = _load_banner_b64("email-header.png")
_BANNER_FOOTER_B64 = _load_banner_b64("email-footer.png")


def banner_attachments() -> list[dict]:
    """Inline header/footer banner attachments to embed in a Resend email."""
    atts: list[dict] = []
    if _BANNER_HEADER_B64:
        atts.append({"filename": "email-header.png", "content": _BANNER_HEADER_B64,
                     "content_id": HEADER_CID, "content_type": "image/png"})
    if _BANNER_FOOTER_B64:
        atts.append({"filename": "email-footer.png", "content": _BANNER_FOOTER_B64,
                     "content_id": FOOTER_CID, "content_type": "image/png"})
    return atts


def wrap_branded_email(body_html: str, footer_note: str = "") -> str:
    """Wrap a transactional email body with the same banner header/footer that
    the prospection campaign uses. Keeps look-and-feel consistent across ALL
    Portech outbound emails (POs, BOLs, invoices, reminders, expense recaps).

    `body_html` is the actual message content (Bonjour ... + paragraphs).
    `footer_note` is the small grey text under the bottom banner (e.g.,
    a unsubscribe hint or document number for traceability).

    Banners are referenced via `cid:` so callers MUST attach `banner_attachments()`
    to the Resend params for the images to render.
    """
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="font-family: Arial, Helvetica, sans-serif; background:#f4f4f5; padding:0; margin:0;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff; max-width:600px;">'
        '<tr><td><img src="cid:' + HEADER_CID + '" alt="Portech" '
        'style="display:block; width:100%; max-width:600px; height:auto; border:0;"/></td></tr>'
        '<tr><td style="padding:32px 32px 16px 32px; color:#0c182b; font-size:15px; line-height:1.6;">'
        + body_html
        + '<p style="margin:24px 0 4px 0;"><b><a href="tel:+14383764177" '
          'style="color:#0c182b; text-decoration:none;">438-376-4177</a> '
          '&middot; <a href="sms:+14383764177" style="color:#2f4f7f; text-decoration:none;">texto</a></b></p>'
        + '<p style="margin:0 0 24px 0;"><a href="https://www.portech.info" '
          'style="color:#1d4ed8;">www.portech.info</a></p>'
        + '<p style="margin:16px 0 0 0;"><b>Cédrick Pimparé</b><br/>'
          'Portech — Quincaillerie et portes commerciales en aluminium</p>'
        + '</td></tr>'
        + '<tr><td><img src="cid:' + FOOTER_CID + '" alt="Portech" '
          'style="display:block; width:100%; max-width:600px; height:auto; border:0;"/></td></tr>'
        + (
            '<tr><td style="padding:16px 32px; color:#71717a; font-size:11px; text-align:center;">'
            + footer_note + '</td></tr>'
            if footer_note else ''
        )
        + '</table></td></tr></table>'
    )


# ---------- Tax math ----------
def compute_totals(items: List[LineItem], taxable: bool = True):
    """Mutate items in place to set .total, then return (subtotal, tps, tvq, total).
    Calcul en Decimal (ROUND_HALF_UP) — source unique via erp_pricing.money."""
    from decimal import Decimal
    from erp_pricing import money, D
    subtotal = Decimal("0")
    for it in items:
        t = money(D(it.quantity) * D(it.unit_price))
        it.total = float(t)
        subtotal += t
    subtotal = money(subtotal)
    if taxable:
        tps = money(subtotal * D(str(TPS_RATE)))
        tvq = money(subtotal * D(str(TVQ_RATE)))
    else:
        tps = Decimal("0")
        tvq = Decimal("0")
    total = money(subtotal + tps + tvq)
    return float(subtotal), float(tps), float(tvq), float(total)


# ---------- Sequential numbering ----------
# Compteur → (collection, champ numéro entier) : sert à l'auto-réparation.
_COUNTER_TARGETS = {
    "invoice": ("erp_invoices", "number"),
    "quote": ("erp_quotes", "number"),
    "purchase_order": ("erp_purchase_orders", "number"),
    "bill_of_lading": ("erp_bills_of_lading", "number"),
    "expert_report": ("erp_expert_reports", "number"),
}


def make_next_number_fn(db: AsyncIOMotorDatabase):
    """Return an async `next_number(counter_type)` closure bound to the given DB.

    Auto-réparation : si le compteur est en retard sur les documents existants
    (ex. base restaurée sans la collection `counters`, ou compteur effacé), le
    numéro obtenu existerait déjà → l'index unique refusait l'insertion et la
    création de facture/soumission plantait (erreur 500) à chaque essai. On
    réaligne alors le compteur sur le plus grand numéro existant + 1."""
    async def _bump(counter_type: str) -> int:
        doc = await db.counters.find_one_and_update(
            {"type": counter_type},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return int(doc["value"])

    async def next_number(counter_type: str) -> int:
        n = await _bump(counter_type)
        target = _COUNTER_TARGETS.get(counter_type)
        if not target:
            return n
        coll, field = target
        if not await db[coll].find_one({field: n}, {"_id": 1}):
            return n
        top = await db[coll].find_one({field: {"$type": "number"}}, {field: 1},
                                      sort=[(field, -1)])
        highest = int((top or {}).get(field) or 0)
        # $max : n'abaisse jamais le compteur, sûr en accès concurrent.
        await db.counters.update_one({"type": counter_type},
                                     {"$max": {"value": highest}}, upsert=True)
        logging.getLogger("portech.erp").warning(
            "Compteur « %s » en retard (numéro %d déjà utilisé) — réaligné sur %d.",
            counter_type, n, highest)
        return await _bump(counter_type)
    return next_number


# ---------- CSV ----------
def csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    if not rows:
        return StreamingResponse(
            iter([""]), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------- Email ----------
async def send_pdf_email(*, to_email: str, subject: str, html: str,
                        pdf_bytes: bytes, filename: str,
                        branded: bool = True,
                        footer_note: str = "",
                        email_type: str = "autre",
                        linked_document: Optional[dict] = None,
                        trigger: str = "user") -> None:
    """Send a transactional email with a PDF attachment via Resend.

    Tout passe par le journal des courriels (`journaled_send`) : une entrée est
    écrite avant et après l'envoi ; un envoi sans journal échoue.
    """
    if not resend.api_key:
        raise HTTPException(503, "Service courriel non configuré (RESEND_API_KEY manquante)")
    from erp_email_journal import journaled_send
    html = normalize_message_to_html(html)
    final_html = wrap_branded_email(html, footer_note=footer_note) if branded else html
    resend_attachments = [{
        "filename": filename,
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
    }]
    if branded:
        resend_attachments += banner_attachments()
    await journaled_send(
        to_email=to_email, subject=subject, final_html=final_html,
        resend_attachments=resend_attachments,
        journal_attachments=[(filename, pdf_bytes, "application/pdf")],
        email_type=email_type, linked_document=linked_document, trigger=trigger)


async def send_html_email(*, to_email: str, subject: str, html: str,
                          branded: bool = True, footer_note: str = "",
                          email_type: str = "autre",
                          linked_document: Optional[dict] = None,
                          trigger: str = "user") -> None:
    """Send a plain transactional email (no attachment) via Resend, journalisé."""
    if not resend.api_key:
        raise HTTPException(503, "Service courriel non configuré (RESEND_API_KEY manquante)")
    from erp_email_journal import journaled_send
    html = normalize_message_to_html(html)
    final_html = wrap_branded_email(html, footer_note=footer_note) if branded else html
    resend_attachments = banner_attachments() if branded else []
    await journaled_send(
        to_email=to_email, subject=subject, final_html=final_html,
        resend_attachments=resend_attachments, journal_attachments=[],
        email_type=email_type, linked_document=linked_document, trigger=trigger)


# ---------- Date parsing ----------
def parse_date_safe(d) -> Optional[datetime]:
    """Parse an ISO date string (YYYY-MM-DD) into a tz-aware datetime, or None."""
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None
