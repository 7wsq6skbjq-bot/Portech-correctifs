"""PDF « Devis de travaux » remis au sous-traitant (format lettre, portrait).

Mise en page pensée pour être lue sur un téléphone ou imprimée sur le chantier :
lieu et contact en haut, problème du client bien en évidence, travaux en cases
à cocher, puis matériel, consignes, rémunération, photos et signatures.
"""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (Flowable, Image, KeepTogether, Paragraph,
                                Spacer, Table, TableStyle)

from erp_pdf import (BG_LIGHT, NAVY, NAVY_BORDER, TEXT_MUTED,
                     _build_doc, _date_fr, _header, _meta_grid, _party_block,
                     _styles)

RED = colors.HexColor("#b3261e")
RED_BG = colors.HexColor("#fdf1ef")
FULL_W = 175 * mm


class _CheckBox(Flowable):
    """Case à cocher dessinée (ne dépend d'aucune police)."""

    def __init__(self, checked=False, size=3.6 * mm):
        super().__init__()
        self.checked, self.size = checked, size
        self.width = self.height = size

    def draw(self):
        c = self.canv
        c.setStrokeColor(NAVY)
        c.setLineWidth(0.9)
        c.rect(0, 0, self.size, self.size, stroke=1, fill=0)
        if self.checked:
            c.setLineWidth(1.3)
            c.line(self.size * 0.18, self.size * 0.5, self.size * 0.42, self.size * 0.2)
            c.line(self.size * 0.42, self.size * 0.2, self.size * 0.85, self.size * 0.85)


def _txt(v) -> str:
    """Texte sûr pour Paragraph (échappé, retours de ligne conservés)."""
    return escape(str(v or "")).replace("\n", "<br/>")


def _section(s, title: str):
    t = Table([[Paragraph(f"<b>{escape(title.upper())}</b>", s["sec"])]], colWidths=[FULL_W])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _box(content, bg=BG_LIGHT, border=NAVY_BORDER, left_bar=None):
    t = Table([[content]], colWidths=[FULL_W])
    style = [
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.5, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    if left_bar is not None:
        style.append(("LINEBEFORE", (0, 0), (0, -1), 3, left_bar))
    t.setStyle(TableStyle(style))
    return t


def _money(v) -> str:
    try:
        return f"{float(v):,.2f} $".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def render_work_order_pdf(wo: dict, photos: list[dict] | None = None) -> bytes:
    s = _styles()
    from reportlab.lib.styles import ParagraphStyle
    s["sec"] = ParagraphStyle("sec", parent=s["body"], fontName="Helvetica-Bold",
                              fontSize=9.5, textColor=NAVY, leading=12)
    s["big"] = ParagraphStyle("big", parent=s["body"], fontSize=10.5, leading=14)
    s["small"] = ParagraphStyle("small", parent=s["body"], fontSize=8, leading=10,
                                textColor=TEXT_MUTED)
    buf, doc = _build_doc()
    story = []
    number = wo.get("number") or "DT"
    status = wo.get("status") or ""
    shown_status = None if status == "brouillon" else status
    story.append(_header(s, "DEVIS DE TRAVAUX", number, shown_status))
    story.append(Spacer(1, 5 * mm))

    if (wo.get("priority") or "") == "urgente":
        story.append(_box(Paragraph("<b>URGENT</b> — intervention prioritaire.", s["big"]),
                          bg=RED_BG, border=RED, left_bar=RED))
        story.append(Spacer(1, 3 * mm))

    # Sous-traitant + infos de planification
    sub = _party_block(s, "Sous-traitant", wo.get("subcontractor_snapshot") or {})
    meta_rows = [
        ("Numéro", number),
        ("Émis le", _date_fr(wo.get("date"))),
        ("Date prévue", _date_fr(wo.get("scheduled_date")) if wo.get("scheduled_date") else "À confirmer"),
        ("Plage horaire", escape(wo.get("scheduled_window") or "—")),
        ("Durée estimée", escape(wo.get("estimated_duration") or "—")),
    ]
    if wo.get("job_number"):
        meta_rows.append(("Réf. Portech", escape(wo["job_number"])))
    if wo.get("client_reference"):
        meta_rows.append(("Réf. client", escape(wo["client_reference"])))
    meta = _meta_grid(s, meta_rows)
    t = Table([[sub, meta]], colWidths=[85 * mm, 90 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(t)

    # Lieu de l'intervention
    site = wo.get("site") or {}
    story.append(_section(s, "Lieu de l'intervention"))
    addr = ", ".join(x for x in (site.get("address"), site.get("city"), site.get("postal_code")) if x)
    left = []
    if site.get("site_name"):
        left.append(f"<b>{_txt(site['site_name'])}</b>")
    if site.get("client_name"):
        left.append(f"Client : {_txt(site['client_name'])}")
    left.append(f"Adresse : <b>{_txt(addr) or '—'}</b>")
    if site.get("door_reference"):
        left.append(f"Porte / équipement : {_txt(site['door_reference'])}")
    right = [
        f"Contact sur place : <b>{_txt(site.get('contact_name')) or '—'}</b>",
        f"Téléphone : <b>{_txt(site.get('contact_phone')) or '—'}</b>",
    ]
    lt = Table([[Paragraph("<br/>".join(left), s["body"]),
                 Paragraph("<br/>".join(right), s["body"])]],
               colWidths=[105 * mm, 70 * mm])
    lt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Spacer(1, 2 * mm))
    story.append(lt)
    if site.get("access_notes"):
        story.append(Spacer(1, 2 * mm))
        story.append(_box(Paragraph(f"<b>Accès / stationnement / horaires :</b><br/>{_txt(site['access_notes'])}",
                                    s["body"])))

    # Problème du client
    story.append(_section(s, "Problème rapporté par le client"))
    story.append(Spacer(1, 2 * mm))
    story.append(_box(Paragraph(_txt(wo.get("complaint")) or "—", s["big"]),
                      bg=RED_BG, border=colors.HexColor("#f0c9c4"), left_bar=RED))
    if wo.get("diagnosis"):
        story.append(_section(s, "Constat / cause probable"))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(_txt(wo["diagnosis"]), s["body"]))

    # Travaux à effectuer
    tasks = wo.get("tasks") or []
    story.append(_section(s, "Travaux à effectuer"))
    if tasks:
        rows = []
        for i, tk in enumerate(tasks, 1):
            rows.append([_CheckBox(bool(tk.get("done"))),
                         Paragraph(f"<b>{i}.</b> {_txt(tk.get('description'))}", s["big"])])
        tt = Table(rows, colWidths=[9 * mm, FULL_W - 9 * mm])
        tt.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, NAVY_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(tt)
    else:
        story.append(Paragraph("—", s["body"]))

    # Matériel
    mats = wo.get("materials") or []
    if mats:
        story.append(_section(s, "Matériel"))
        rows = [[Paragraph("<b>Description</b>", s["small"]), Paragraph("<b>Qté</b>", s["small"]),
                 Paragraph("<b>Fourni par</b>", s["small"])]]
        for m in mats:
            rows.append([Paragraph(_txt(m.get("description")), s["body"]),
                         Paragraph(_txt(m.get("qty") or "1"), s["body"]),
                         Paragraph(_txt(m.get("supplied_by") or "Portech"), s["body"])])
        mt = Table(rows, colWidths=[120 * mm, 20 * mm, 35 * mm], repeatRows=1)
        mt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BG_LIGHT),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, NAVY_BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(Spacer(1, 2 * mm))
        story.append(mt)

    # Consignes
    if (wo.get("instructions") or "").strip():
        story.append(_section(s, "Consignes"))
        lines = [ln.strip() for ln in wo["instructions"].splitlines() if ln.strip()]
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph("<br/>".join(f"• {_txt(ln)}" for ln in lines), s["body"]))

    # Rémunération
    if wo.get("show_pay_on_pdf", True):
        mode = wo.get("pay_mode") or "à confirmer"
        amt = float(wo.get("pay_amount") or 0)
        if mode == "forfait" and amt > 0:
            pay = f"Forfait convenu : <b>{_money(amt)}</b> (taxes en sus)"
        elif mode == "taux horaire" and amt > 0:
            pay = f"Taux horaire : <b>{_money(amt)} / h</b> (taxes en sus)"
            if float(wo.get("pay_max_hours") or 0) > 0:
                pay += f" — maximum <b>{float(wo['pay_max_hours']):g} h</b> sans autorisation"
        else:
            pay = "Rémunération : <b>à confirmer avec Portech avant le début des travaux</b>"
        if wo.get("pay_notes"):
            pay += f"<br/>{_txt(wo['pay_notes'])}"
        story.append(_section(s, "Rémunération"))
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph(pay, s["body"]))

    # Photos (2 par rangée)
    photos = photos or []
    if photos:
        story.append(_section(s, "Photos"))
        story.append(Spacer(1, 2 * mm))
        cells, row = [], []
        col_w = (FULL_W - 6 * mm) / 2
        for ph in photos:
            try:
                from PIL import Image as PILImage
                pim = PILImage.open(io.BytesIO(ph["bytes"]))
                w, h = pim.size
                draw_w = col_w
                draw_h = min(draw_w * h / w, 85 * mm)
                draw_w = draw_h * w / h
                img = Image(io.BytesIO(ph["bytes"]), width=draw_w, height=draw_h)
            except Exception:
                continue
            row.append([img, Paragraph(_txt(ph.get("caption")), s["small"])])
            if len(row) == 2:
                cells.append(row)
                row = []
        if row:
            row.append("")
            cells.append(row)
        if cells:
            pt = Table(cells, colWidths=[col_w + 3 * mm, col_w + 3 * mm])
            pt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(pt)

    # Signatures
    sig_style = TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ])
    acc = Table([[Paragraph("<b>ACCEPTATION DU SOUS-TRAITANT</b><br/><br/>"
                            "Nom : ______________________________<br/><br/>"
                            "Signature : __________________________<br/><br/>"
                            "Date : ______________", s["body"]),
                  Paragraph("<b>FIN DES TRAVAUX</b><br/><br/>"
                            "Terminé le : _____________  Heures : ______<br/><br/>"
                            "Problème réglé :&nbsp;&nbsp;[&nbsp;&nbsp;&nbsp;] oui&nbsp;&nbsp;&nbsp;&nbsp;[&nbsp;&nbsp;&nbsp;] non<br/><br/>"
                            "Remarques : _________________________", s["body"])]],
                colWidths=[FULL_W / 2, FULL_W / 2])
    acc.setStyle(sig_style)
    story.append(Spacer(1, 6 * mm))
    story.append(KeepTogether([acc]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Document confidentiel remis au sous-traitant pour cette intervention seulement. "
        "Pour toute question ou tout imprévu sur le chantier, communiquez avec Portech "
        "avant d'aller plus loin — info@portech.info.", s["small"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()

