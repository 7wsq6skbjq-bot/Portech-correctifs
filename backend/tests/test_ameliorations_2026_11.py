"""Tests hors-ligne (aucun serveur, aucune base) des corrections de novembre 2026.

Lancer :  cd backend && python -m pytest tests/test_ameliorations_2026_11.py -q
"""
import copy
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test")

import erp_pdf_production as P  # noqa: E402

BASE_DOOR = {
    "tag": "P1", "series": "AT1000", "config": "simple",
    "opening_width_in": 36, "opening_height_in": 84, "qty": 1, "handing": "MD",
    "hinge_type": "butt45", "hardware": [],
}


def _plan(**door_over):
    d = copy.deepcopy(BASE_DOOR)
    d.update(door_over)
    return {"project_name": "Test", "client_name": "Client", "doors": [d],
            "include_plan_details": False, "include_section_details": False,
            "include_anchors": False}


def _pdf_text(pdf_bytes):
    import io
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_bytes)).pages)


def test_inch_fraction_never_shows_16_16():
    assert P._inch_fmt(35.98) == '36"'          # avant : 35 1/1"
    assert P._inch_fmt(34.5) == '34 1/2"'
    assert P._inch_fmt(62.94) == '62 15/16"'


def test_hardware_detection_p33_and_paddle():
    door = {"hardware": [{"description": "POIGNÉE À TIRER 12 - BARRE A POUSSER 33", "part_number": "P33-SA"}]}
    assert P._hw_implies_push_bar(door)
    assert not P._hw_implies_paddle(door)
    door = {"hardware": [{"description": "PALETTE DE RELÂCHE", "part_number": "ADAM-45900200628"}]}
    assert P._hw_implies_paddle(door)
    door = {"hardware": [{"description": "PALETTE DE RELÂCHE", "included": False}]}
    assert not P._hw_implies_paddle(door)


def test_plan_with_push_bar_and_paddle_renders():
    for over in ({"push_bar": True}, {"push_paddle": True},
                 {"push_bar": True, "push_paddle": True, "handing": "MDR"},
                 {"config": "pair", "opening_width_in": 72, "push_bar": True,
                  "push_bar_leaf": "both", "push_paddle": True, "paddle_leaf": "both"}):
        pdf = P.render_production_plan_pdf(_plan(**over))
        assert pdf[:4] == b"%PDF"


def test_push_bar_dimension_shown_p33_is_33_inches():
    pdf = P.render_production_plan_pdf(_plan(hardware=[{"description": "P33", "part_number": "P33-SA"}]))
    assert '838.2 [33"] c/c' in _pdf_text(pdf)


def test_cover_has_door_summary():
    pdf = P.render_production_plan_pdf(_plan())
    assert "SOMMAIRE DES PORTES" in _pdf_text(pdf)


def test_same_height_dimension_not_repeated():
    # serrure à 40" et palette à 40" : une seule cote 40" sur le vantail
    pdf = P.render_production_plan_pdf(_plan(push_paddle=True, paddle_height_in=40, lock_height_in=40,
                                             show_handle=False))
    txt = _pdf_text(pdf)
    assert txt.count('1016.0 [40"]') == 1


def test_swing_symbol_on_elevation_all_hands():
    for hand in ("MD", "MG", "MDR", "MGR"):
        for cfg, w in (("simple", 36), ("pair", 72)):
            pdf = P.render_production_plan_pdf(_plan(handing=hand, config=cfg, opening_width_in=w))
            assert f"Sens d'ouverture — {hand}" in _pdf_text(pdf)


def test_detail_pages_have_no_interior_exterior_mentions():
    plan = _plan(handing="MDR")
    plan.update(include_plan_details=True, include_section_details=True, include_anchors=True)
    import io
    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(P.render_production_plan_pdf(plan))).pages
    details = "\n".join((pg.extract_text() or "") for pg in pages[2:]).upper()
    for word in ("CORRIDOR", "VESTIBULE", "INTÉRIEUR", "EXTÉRIEUR", "OUVRANT"):
        assert word not in details


def test_push_bar_hidden_for_reverse_hands():
    # MDR / MGR : la barre à pousser est de l'autre côté → trait pointillé.
    import reportlab.pdfgen.canvas as cv
    calls = []
    orig = cv.Canvas.setDash

    def spy(self, *a, **k):
        calls.append(a)
        return orig(self, *a, **k)
    cv.Canvas.setDash = spy
    try:
        P.render_production_plan_pdf(_plan(handing="MDR", push_bar=True, show_handle=False, show_lock=False))
        n_rev = len(calls)
        calls.clear()
        P.render_production_plan_pdf(_plan(handing="MD", push_bar=True, show_handle=False, show_lock=False))
        n_norm = len(calls)
    finally:
        cv.Canvas.setDash = orig
    assert n_rev > n_norm


def test_work_order_pdf_renders_without_internal_notes():
    from erp_pdf_work_order import render_work_order_pdf
    wo = {
        "number": "DT-2026-999", "status": "envoyé", "priority": "urgente",
        "subcontractor_snapshot": {"name": "Sous-traitant test", "email": "a@b.ca"},
        "date": "2026-11-12", "scheduled_date": "2026-11-14", "scheduled_window": "7 h à 9 h",
        "site": {"client_name": "Client X", "site_name": "Entrée principale", "address": "1 rue A",
                 "city": "Laval", "contact_name": "Julie", "contact_phone": "450-555-0000",
                 "access_notes": "Quai arrière"},
        "complaint": "La porte claque & ne se barre plus <vraiment>.",
        "tasks": [{"description": "Remplacer le ferme-porte", "done": False},
                  {"description": "Régler la gâche", "done": True}],
        "materials": [{"description": "LCN 4040XP", "qty": "1", "supplied_by": "Portech"}],
        "pay_mode": "forfait", "pay_amount": 275,
        "internal_notes": "PRIX CLIENT 485 SECRET",
    }
    pdf = render_work_order_pdf(wo, [])
    txt = _pdf_text(pdf)
    assert pdf[:4] == b"%PDF"
    assert "DEVIS DE" in txt and "La porte claque & ne se barre plus <vraiment>." in txt
    assert "PRIX CLIENT" not in txt
    assert "275,00 $" in txt
