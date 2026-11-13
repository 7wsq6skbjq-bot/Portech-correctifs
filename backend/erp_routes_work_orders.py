"""Devis de travaux pour sous-traitant (bon de travail) — CRUD + photos + PDF + courriel.

Quand Portech engage un sous-traitant, ce document lui donne en une page claire :
  * le LIEU de l'intervention (adresse, contact sur place, accès, stationnement) ;
  * le PROBLÈME ou la plainte du client, dans ses mots ;
  * le constat / diagnostic connu ;
  * la liste des TRAVAUX à effectuer (cases à cocher) et le matériel ;
  * les consignes, la rémunération convenue, des photos, et un bloc de signature.

Numérotation : DT-AAAA-NNN (compteur annuel dans `erp_counters`).
Les notes internes et le prix facturé au client ne sont JAMAIS imprimés.
"""
from __future__ import annotations

import asyncio
import io
import logging
import uuid
from datetime import date as DateT, datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from erp_helpers import send_pdf_email
from erp_models import Party

logger = logging.getLogger("portech.erp.work_orders")

PHOTO_BUCKET = "work_order_photos"
MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 15 * 1024 * 1024

WorkOrderStatus = Literal["brouillon", "envoyé", "accepté", "en cours", "terminé", "annulé"]
PayMode = Literal["forfait", "taux horaire", "à confirmer"]

DEFAULT_INSTRUCTIONS = (
    "Prendre des photos AVANT et APRÈS les travaux et les envoyer à Portech.\n"
    "Aucun travail supplémentaire sans l'autorisation écrite de Portech.\n"
    "Appeler Portech avant de quitter si le problème n'est pas réglé.\n"
    "Laisser les lieux propres ; rapporter les pièces remplacées.\n"
    "Respecter les règles de sécurité et d'accès du site."
)


class WorkTask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = Field(min_length=1, max_length=1000)
    done: bool = False


class WorkMaterial(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = Field(min_length=1, max_length=500)
    qty: str = "1"
    supplied_by: Literal["Portech", "Sous-traitant"] = "Portech"


class WorkPhoto(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    filename: str = ""
    caption: str = ""
    content_type: str = "image/jpeg"


class WorkSite(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_name: str = ""
    site_name: str = ""                 # ex. « Uniprix St-Martin — entrée principale »
    address: str = ""
    city: str = ""
    postal_code: str = ""
    contact_name: str = ""              # contact sur place
    contact_phone: str = ""
    access_notes: str = ""              # heures d'accès, clé, code, stationnement, quai…
    door_reference: str = ""            # ex. « Porte P1 — double, aluminium noir »


class WorkOrderIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subcontractor_id: Optional[str] = None
    subcontractor_snapshot: Party
    date: DateT = Field(default_factory=DateT.today)
    scheduled_date: Optional[DateT] = None
    scheduled_window: str = ""          # ex. « 7 h – 9 h, avant l'ouverture »
    estimated_duration: str = ""        # ex. « 2 à 3 h »
    priority: Literal["normale", "urgente"] = "normale"
    status: WorkOrderStatus = "brouillon"
    site: WorkSite = Field(default_factory=WorkSite)
    complaint: str = ""                 # problème / plainte du client
    diagnosis: str = ""                 # constat / cause probable
    tasks: List[WorkTask] = Field(default_factory=list)
    materials: List[WorkMaterial] = Field(default_factory=list)
    instructions: str = DEFAULT_INSTRUCTIONS
    pay_mode: PayMode = "à confirmer"
    pay_amount: float = Field(default=0, ge=0)   # forfait ($) ou taux ($/h)
    pay_max_hours: float = Field(default=0, ge=0)
    pay_notes: str = ""
    show_pay_on_pdf: bool = True
    job_id: Optional[str] = None
    job_number: str = ""
    client_reference: str = ""          # n° de bon de commande / soumission du client
    internal_notes: str = ""            # JAMAIS sur le PDF


class WorkOrder(WorkOrderIn):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    number: str = ""                    # DT-2026-001
    photos: List[WorkPhoto] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at: Optional[datetime] = None
    sent_to: Optional[str] = None


class WorkOrderEmailRequest(BaseModel):
    to_email: EmailStr
    subject: Optional[str] = None
    message: Optional[str] = None


def _bucket(db) -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db, bucket_name=PHOTO_BUCKET)


def _shrink_image(raw: bytes) -> tuple[bytes, str]:
    """Réduit une photo (max 1600 px, JPEG) pour garder des PDF légers."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue(), "image/jpeg"


async def load_photo_bytes(db, photo_id: str) -> Optional[bytes]:
    bucket = _bucket(db)
    docs = await bucket.find({"metadata.photo_id": photo_id}).to_list(1)
    if not docs:
        return None
    stream = await bucket.open_download_stream(docs[0]._id)
    return await stream.read()


async def _photos_for_pdf(db, wo: dict) -> list[dict]:
    out = []
    for p in wo.get("photos") or []:
        data = await load_photo_bytes(db, p.get("id"))
        if data:
            out.append({"bytes": data, "caption": p.get("caption") or ""})
    return out


def register(router: APIRouter, db: AsyncIOMotorDatabase, auth_dep) -> None:

    async def _next_number() -> str:
        year = datetime.now(timezone.utc).year
        counter = await db.erp_counters.find_one_and_update(
            {"key": f"work_order_{year}"}, {"$inc": {"seq": 1}},
            upsert=True, return_document=True,
        )
        seq = int((counter or {}).get("seq") or 1)
        number = f"DT-{year}-{seq:03d}"
        # auto-réparation si le compteur est en retard (base restaurée…)
        while await db.erp_work_orders.find_one({"number": number}, {"_id": 1}):
            counter = await db.erp_counters.find_one_and_update(
                {"key": f"work_order_{year}"}, {"$inc": {"seq": 1}},
                upsert=True, return_document=True)
            number = f"DT-{year}-{int(counter.get('seq') or 1):03d}"
        return number

    async def _get(wo_id: str) -> dict:
        doc = await db.erp_work_orders.find_one({"id": wo_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "Devis de travaux introuvable")
        return doc

    @router.get("/work-orders", response_model=List[WorkOrder])
    async def list_work_orders(_: dict = Depends(auth_dep)):
        cur = db.erp_work_orders.find({}, {"_id": 0}).sort("created_at", -1)
        return [WorkOrder(**d) async for d in cur]

    @router.post("/work-orders", response_model=WorkOrder, status_code=201)
    async def create_work_order(data: WorkOrderIn, _: dict = Depends(auth_dep)):
        wo = WorkOrder(**data.model_dump(), number=await _next_number())
        await db.erp_work_orders.insert_one(wo.model_dump(mode="json"))
        return wo

    @router.get("/work-orders/{wo_id}", response_model=WorkOrder)
    async def get_work_order(wo_id: str, _: dict = Depends(auth_dep)):
        return WorkOrder(**await _get(wo_id))

    @router.put("/work-orders/{wo_id}", response_model=WorkOrder)
    async def update_work_order(wo_id: str, data: WorkOrderIn, _: dict = Depends(auth_dep)):
        await _get(wo_id)
        fields = data.model_dump(mode="json")
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.erp_work_orders.update_one({"id": wo_id}, {"$set": fields})
        return WorkOrder(**await _get(wo_id))

    @router.delete("/work-orders/{wo_id}", status_code=204)
    async def delete_work_order(wo_id: str, _: dict = Depends(auth_dep)):
        doc = await _get(wo_id)
        bucket = _bucket(db)
        for p in doc.get("photos") or []:
            async for gf in bucket.find({"metadata.photo_id": p.get("id")}):
                await bucket.delete(gf._id)
        await db.erp_work_orders.delete_one({"id": wo_id})
        return Response(status_code=204)

    @router.post("/work-orders/{wo_id}/duplicate", response_model=WorkOrder, status_code=201)
    async def duplicate_work_order(wo_id: str, _: dict = Depends(auth_dep)):
        """Copie le devis (sans photos) — pratique pour un 2e passage ou un autre sous-traitant."""
        src = await _get(wo_id)
        data = WorkOrderIn(**src).model_dump()
        data.update(status="brouillon", scheduled_date=None)
        for t in data.get("tasks") or []:
            t["done"] = False
        wo = WorkOrder(**data, number=await _next_number())
        await db.erp_work_orders.insert_one(wo.model_dump(mode="json"))
        return wo

    # ── Photos ──
    @router.post("/work-orders/{wo_id}/photos", response_model=WorkOrder)
    async def add_photo(wo_id: str, file: UploadFile = File(...), caption: str = Form(""),
                        _: dict = Depends(auth_dep)):
        doc = await _get(wo_id)
        if len(doc.get("photos") or []) >= MAX_PHOTOS:
            raise HTTPException(400, f"Maximum {MAX_PHOTOS} photos par devis.")
        raw = await file.read()
        if not raw:
            raise HTTPException(400, "Fichier vide.")
        if len(raw) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "Photo trop lourde (max 15 Mo).")
        try:
            data, ctype = await asyncio.to_thread(_shrink_image, raw)
        except Exception:
            raise HTTPException(400, "Format d'image non reconnu (JPEG, PNG, HEIC converti…).")
        photo_id = uuid.uuid4().hex
        await _bucket(db).upload_from_stream(
            file.filename or f"{photo_id}.jpg", data,
            metadata={"photo_id": photo_id, "work_order_id": wo_id,
                      "content_type": ctype,
                      "uploaded_at": datetime.now(timezone.utc).isoformat()})
        photo = WorkPhoto(id=photo_id, filename=file.filename or "", caption=caption[:200],
                          content_type=ctype)
        await db.erp_work_orders.update_one(
            {"id": wo_id}, {"$push": {"photos": photo.model_dump()}})
        return WorkOrder(**await _get(wo_id))

    @router.get("/work-orders/{wo_id}/photos/{photo_id}")
    async def get_photo(wo_id: str, photo_id: str, _: dict = Depends(auth_dep)):
        data = await load_photo_bytes(db, photo_id)
        if not data:
            raise HTTPException(404, "Photo introuvable")
        return Response(content=data, media_type="image/jpeg")

    @router.patch("/work-orders/{wo_id}/photos/{photo_id}", response_model=WorkOrder)
    async def caption_photo(wo_id: str, photo_id: str, body: dict, _: dict = Depends(auth_dep)):
        await _get(wo_id)
        await db.erp_work_orders.update_one(
            {"id": wo_id, "photos.id": photo_id},
            {"$set": {"photos.$.caption": str((body or {}).get("caption") or "")[:200]}})
        return WorkOrder(**await _get(wo_id))

    @router.delete("/work-orders/{wo_id}/photos/{photo_id}", response_model=WorkOrder)
    async def delete_photo(wo_id: str, photo_id: str, _: dict = Depends(auth_dep)):
        await _get(wo_id)
        bucket = _bucket(db)
        async for gf in bucket.find({"metadata.photo_id": photo_id}):
            await bucket.delete(gf._id)
        await db.erp_work_orders.update_one({"id": wo_id}, {"$pull": {"photos": {"id": photo_id}}})
        return WorkOrder(**await _get(wo_id))

    # ── PDF + courriel ──
    async def _render(doc: dict) -> bytes:
        from erp_pdf_work_order import render_work_order_pdf
        photos = await _photos_for_pdf(db, doc)
        return await asyncio.to_thread(render_work_order_pdf, doc, photos)

    @router.get("/work-orders/{wo_id}/pdf")
    async def work_order_pdf(wo_id: str, _: dict = Depends(auth_dep)):
        doc = await _get(wo_id)
        pdf = await _render(doc)
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{doc.get("number") or "DT"}.pdf"'})

    @router.post("/work-orders/{wo_id}/send-email")
    async def send_work_order(wo_id: str, payload: WorkOrderEmailRequest,
                              _: dict = Depends(auth_dep)):
        doc = await _get(wo_id)
        pdf = await _render(doc)
        number = doc.get("number") or "DT"
        sub = (doc.get("subcontractor_snapshot") or {}).get("name") or ""
        site = doc.get("site") or {}
        where = ", ".join(x for x in (site.get("site_name"), site.get("address"), site.get("city")) if x)
        when = doc.get("scheduled_date") or "à confirmer"
        subject = payload.subject or f"Portech — Devis de travaux {number}" + (f" — {site.get('city')}" if site.get("city") else "")
        html = payload.message or (
            f"<p>Bonjour {sub},</p>"
            f"<p>Vous trouverez en pièce jointe le <b>devis de travaux {number}</b>.</p>"
            f"<p><b>Lieu :</b> {where or '—'}<br/><b>Date prévue :</b> {when}"
            + (f" ({doc.get('scheduled_window')})" if doc.get("scheduled_window") else "")
            + "</p><p>Merci de confirmer votre disponibilité en répondant à ce courriel. "
            "Prenez des photos avant et après les travaux.</p>"
        )
        await send_pdf_email(
            to_email=payload.to_email, subject=subject, html=html,
            pdf_bytes=pdf, filename=f"{number}.pdf",
            footer_note=f"Devis de travaux {number} · Portech",
            email_type="autre",
            linked_document={"kind": "work_order", "id": wo_id, "label": number,
                             "customer": site.get("client_name")},
        )
        upd = {"sent_at": datetime.now(timezone.utc).isoformat(), "sent_to": payload.to_email}
        if doc.get("status") == "brouillon":
            upd["status"] = "envoyé"
        await db.erp_work_orders.update_one({"id": wo_id}, {"$set": upd})
        return {"sent": True, "to": payload.to_email}
