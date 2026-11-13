/** Devis de travaux pour sous-traitant (bons de travail).
 *
 *  Donne au sous-traitant, sur un seul PDF : le lieu de l'intervention, le contact
 *  sur place, l'accès, le problème rapporté par le client, les travaux à faire
 *  (cases à cocher), le matériel, les consignes, la rémunération et des photos.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    HardHat, Plus, Pencil, Trash2, RefreshCw, Download, Send, Copy, Loader2,
    ArrowUp, ArrowDown, X, ImagePlus, Search,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Modal, Field, inputClass } from "../components/Modal";
import { emptyParty, formatCurrency, formatDate, newKey, localISO } from "../utils";

const STATUSES = ["brouillon", "envoyé", "accepté", "en cours", "terminé", "annulé"];
const STATUS_STYLE = {
    brouillon: "bg-[#f3f6fb] text-[#4b5d7a] border-[#c5d4e7]",
    envoyé: "bg-[#eaf1fb] text-[#2f4f7f] border-[#97b0d0]",
    accepté: "bg-[#e7f0fb] text-[#1d4ed8] border-[#9db9e8]",
    "en cours": "bg-[#fff4e0] text-[#925800] border-[#e5ba67]",
    terminé: "bg-[#e6f4ea] text-[#0b6b2f] border-[#8ec79d]",
    annulé: "bg-[#fbe8e8] text-[#8a1f1f] border-[#e8a5a5]",
};

const DEFAULT_INSTRUCTIONS = [
    "Prendre des photos AVANT et APRÈS les travaux et les envoyer à Portech.",
    "Aucun travail supplémentaire sans l'autorisation écrite de Portech.",
    "Appeler Portech avant de quitter si le problème n'est pas réglé.",
    "Laisser les lieux propres ; rapporter les pièces remplacées.",
    "Respecter les règles de sécurité et d'accès du site.",
].join("\n");

const emptySite = () => ({
    client_name: "", site_name: "", address: "", city: "", postal_code: "",
    contact_name: "", contact_phone: "", access_notes: "", door_reference: "",
});

const emptyWorkOrder = () => ({
    subcontractor_id: null,
    subcontractor_snapshot: emptyParty("supplier"),
    date: localISO(),
    scheduled_date: "",
    scheduled_window: "",
    estimated_duration: "",
    priority: "normale",
    status: "brouillon",
    site: emptySite(),
    complaint: "",
    diagnosis: "",
    tasks: [{ _key: newKey(), description: "", done: false }],
    materials: [],
    instructions: DEFAULT_INSTRUCTIONS,
    pay_mode: "à confirmer",
    pay_amount: 0,
    pay_max_hours: 0,
    pay_notes: "",
    show_pay_on_pdf: true,
    job_id: null,
    job_number: "",
    client_reference: "",
    internal_notes: "",
    photos: [],
});

const toForm = (wo) => ({
    ...emptyWorkOrder(),
    ...wo,
    scheduled_date: wo.scheduled_date || "",
    site: { ...emptySite(), ...(wo.site || {}) },
    subcontractor_snapshot: { ...emptyParty("supplier"), ...(wo.subcontractor_snapshot || {}) },
    tasks: (wo.tasks || []).map((t) => ({ ...t, _key: newKey() })),
    materials: (wo.materials || []).map((m) => ({ ...m, _key: newKey() })),
});

const SERVER_ONLY = ["_key", "id", "number", "photos", "created_at", "updated_at", "sent_at", "sent_to"];

const toPayload = (f) => {
    const rest = { ...f };
    SERVER_ONLY.forEach((k) => { delete rest[k]; });
    return {
        ...rest,
        scheduled_date: f.scheduled_date || null,
        pay_amount: Number(f.pay_amount) || 0,
        pay_max_hours: Number(f.pay_max_hours) || 0,
        tasks: (f.tasks || []).filter((t) => (t.description || "").trim())
            .map((t) => ({ description: t.description.trim(), done: !!t.done })),
        materials: (f.materials || []).filter((m) => (m.description || "").trim())
            .map((m) => ({ description: m.description.trim(), qty: String(m.qty || "1"), supplied_by: m.supplied_by || "Portech" })),
    };
};

const Section = ({ title, children, hint }) => (
    <div className="border border-[#dde5f0] p-4 space-y-3">
        <div>
            <div className="tech-stamp text-[#0c182b]">{title}</div>
            {hint && <div className="text-xs text-[#4b5d7a] mt-0.5">{hint}</div>}
        </div>
        {children}
    </div>
);

export const WorkOrdersPanel = () => {
    const { http, getToken } = useAuth();
    const [rows, setRows] = useState([]);
    const [suppliers, setSuppliers] = useState([]);
    const [customers, setCustomers] = useState([]);
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [query, setQuery] = useState("");
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState(emptyWorkOrder());
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    const [notice, setNotice] = useState("");

    const flash = (m) => { setNotice(m); setTimeout(() => setNotice(""), 6000); };

    const load = useCallback(async () => {
        setLoading(true); setError("");
        try {
            const [w, s, c, j] = await Promise.all([
                http.get("/admin/work-orders"),
                http.get("/admin/parties?kind=supplier").catch(() => ({ data: [] })),
                http.get("/admin/parties?kind=customer").catch(() => ({ data: [] })),
                http.get("/admin/jobs").catch(() => ({ data: [] })),
            ]);
            setRows(Array.isArray(w.data) ? w.data : []);
            setSuppliers((Array.isArray(s.data) ? s.data : []).filter((p) => (p.kind || "supplier") === "supplier"));
            setCustomers((Array.isArray(c.data) ? c.data : []).filter((p) => (p.kind || "customer") === "customer"));
            setJobs(Array.isArray(j.data) ? j.data : []);
        } catch (e) {
            setError(e?.response?.data?.detail || "Erreur de chargement.");
        } finally { setLoading(false); }
    }, [http]);

    useEffect(() => { load(); }, [load]);

    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter((r) => [r.number, r.subcontractor_snapshot?.name, r.site?.client_name,
            r.site?.site_name, r.site?.address, r.site?.city, r.complaint]
            .some((v) => (v || "").toLowerCase().includes(q)));
    }, [rows, query]);

    // ── form helpers ──
    const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
    const setSite = (k, v) => setForm((f) => ({ ...f, site: { ...f.site, [k]: v } }));
    const setSub = (k, v) => setForm((f) => ({ ...f, subcontractor_id: k === "name" ? null : f.subcontractor_id,
        subcontractor_snapshot: { ...f.subcontractor_snapshot, [k]: v } }));
    const pickSupplier = (id) => {
        const p = suppliers.find((x) => x.id === id);
        if (!p) return;
        setForm((f) => ({ ...f, subcontractor_id: p.id, subcontractor_snapshot: { ...emptyParty("supplier"), ...p } }));
    };
    const pickCustomer = (id) => {
        const p = customers.find((x) => x.id === id);
        if (!p) return;
        setForm((f) => ({ ...f, site: { ...f.site,
            client_name: p.name || "",
            address: f.site.address || [p.address_line1, p.address_line2].filter(Boolean).join(", "),
            city: f.site.city || p.city || "",
            postal_code: f.site.postal_code || p.postal_code || "",
            contact_name: f.site.contact_name || p.contact || "",
            contact_phone: f.site.contact_phone || p.phone || "",
        } }));
    };
    const pickJob = (id) => {
        const j = jobs.find((x) => x.id === id);
        if (!j) { setForm((f) => ({ ...f, job_id: null, job_number: "" })); return; }
        setForm((f) => ({ ...f, job_id: j.id, job_number: j.job_number || "",
            site: { ...f.site, client_name: f.site.client_name || j.client_name || "" } }));
    };
    const updList = (key, k, field, value) => setForm((f) => ({
        ...f, [key]: f[key].map((x) => (x._key === k ? { ...x, [field]: value } : x)) }));
    const addTask = () => setForm((f) => ({ ...f, tasks: [...f.tasks, { _key: newKey(), description: "", done: false }] }));
    const addMaterial = () => setForm((f) => ({ ...f, materials: [...f.materials, { _key: newKey(), description: "", qty: "1", supplied_by: "Portech" }] }));
    const removeFrom = (key, k) => setForm((f) => ({ ...f, [key]: f[key].filter((x) => x._key !== k) }));
    const move = (key, k, dir) => setForm((f) => {
        const arr = [...f[key]]; const i = arr.findIndex((x) => x._key === k); const j = i + dir;
        if (i < 0 || j < 0 || j >= arr.length) return f;
        [arr[i], arr[j]] = [arr[j], arr[i]];
        return { ...f, [key]: arr };
    });

    const openNew = () => { setForm(emptyWorkOrder()); setError(""); setOpen(true); };
    const openEdit = (wo) => { setForm(toForm(wo)); setError(""); setOpen(true); };

    const save = async (keepOpen = false) => {
        if (!(form.subcontractor_snapshot?.name || "").trim()) { setError("Indiquez le sous-traitant."); return null; }
        if (!(form.site?.address || "").trim()) { setError("Indiquez l'adresse du chantier."); return null; }
        if (!(form.complaint || "").trim()) { setError("Décrivez le problème rapporté par le client."); return null; }
        setBusy("save"); setError("");
        try {
            const payload = toPayload(form);
            const { data } = form.id
                ? await http.put(`/admin/work-orders/${form.id}`, payload)
                : await http.post("/admin/work-orders", payload);
            await load();
            if (keepOpen) setForm(toForm(data)); else setOpen(false);
            flash(`${data.number} enregistré.`);
            return data;
        } catch (e) {
            const d = e?.response?.data?.detail;
            setError(typeof d === "string" ? d : "Échec de l'enregistrement — vérifiez les champs.");
            return null;
        } finally { setBusy(""); }
    };

    const uploadPhotos = async (files) => {
        let current = form;
        if (!current.id) {
            const saved = await save(true);
            if (!saved) return;
            current = saved;
        }
        setBusy("photo"); setError("");
        try {
            let last = null;
            for (const file of files || []) {
                const fd = new FormData();
                fd.append("file", file);
                fd.append("caption", "");
                const { data } = await http.post(`/admin/work-orders/${current.id}/photos`, fd);
                last = data;
            }
            if (last) setForm((f) => ({ ...f, id: last.id, number: last.number, photos: last.photos }));
            await load();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de l'envoi de la photo.");
        } finally { setBusy(""); }
    };
    const captionPhoto = async (pid, caption) => {
        try {
            const { data } = await http.patch(`/admin/work-orders/${form.id}/photos/${pid}`, { caption });
            setForm((f) => ({ ...f, photos: data.photos }));
        } catch { /* silencieux */ }
    };
    const deletePhoto = async (pid) => {
        if (!window.confirm("Retirer cette photo ?")) return;
        const { data } = await http.delete(`/admin/work-orders/${form.id}/photos/${pid}`);
        setForm((f) => ({ ...f, photos: data.photos }));
        load();
    };
    const photoUrl = (wid, pid) => {
        const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
        return `${base}/api/admin/work-orders/${wid}/photos/${pid}?token=${encodeURIComponent(getToken() || "")}`;
    };

    const openPdf = (wo) => {
        const base = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
        const url = `${base}/api/admin/work-orders/${wo.id}/pdf?token=${encodeURIComponent(getToken() || "")}`;
        if (/iPad|iPhone|iPod|Android/i.test(navigator.userAgent)) window.location.href = url; else window.open(url, "_blank");
    };
    const sendEmail = async (wo) => {
        const to = window.prompt(`Envoyer ${wo.number} à quelle adresse ?`, wo.subcontractor_snapshot?.email || "");
        if (!to) return;
        setBusy(`send-${wo.id}`);
        try {
            await http.post(`/admin/work-orders/${wo.id}/send-email`, { to_email: to });
            flash(`${wo.number} envoyé à ${to}.`);
            load();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de l'envoi.");
        } finally { setBusy(""); }
    };
    const duplicate = async (wo) => {
        const { data } = await http.post(`/admin/work-orders/${wo.id}/duplicate`);
        flash(`Copie créée : ${data.number}.`);
        load();
    };
    const remove = async (wo) => {
        if (!window.confirm(`Supprimer ${wo.number} ? Les photos seront aussi supprimées.`)) return;
        await http.delete(`/admin/work-orders/${wo.id}`);
        load();
    };
    const quickStatus = async (wo, status) => {
        const { data } = await http.get(`/admin/work-orders/${wo.id}`);
        await http.put(`/admin/work-orders/${wo.id}`, toPayload({ ...toForm(data), status }));
        load();
    };

    const actions = (wo) => (
        <div className="flex flex-wrap justify-end gap-1">
            <button onClick={() => openPdf(wo)} title="Voir le PDF" data-testid={`wo-pdf-${wo.id}`}
                className="p-2 border border-[#dde5f0] hover:bg-[#eaf1fb] text-[#2f4f7f]"><Download className="w-3.5 h-3.5" /></button>
            <button onClick={() => sendEmail(wo)} title="Envoyer au sous-traitant" data-testid={`wo-send-${wo.id}`}
                disabled={busy === `send-${wo.id}`}
                className="p-2 border border-[#dde5f0] hover:bg-[#eaf1fb] text-[#2f4f7f]">
                {busy === `send-${wo.id}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            </button>
            <button onClick={() => duplicate(wo)} title="Dupliquer" data-testid={`wo-dup-${wo.id}`}
                className="p-2 border border-[#dde5f0] hover:bg-[#eaf1fb] text-[#2f4f7f]"><Copy className="w-3.5 h-3.5" /></button>
            <button onClick={() => openEdit(wo)} title="Modifier" data-testid={`wo-edit-${wo.id}`}
                className="p-2 border border-[#dde5f0] hover:bg-[#eaf1fb] text-[#2f4f7f]"><Pencil className="w-3.5 h-3.5" /></button>
            <button onClick={() => remove(wo)} title="Supprimer" data-testid={`wo-del-${wo.id}`}
                className="p-2 border border-[#e8a5a5] hover:bg-[#fbe8e8] text-[#8a1f1f]"><Trash2 className="w-3.5 h-3.5" /></button>
        </div>
    );

    return (
        <div data-testid="work-orders-panel">
            <div className="flex items-start md:items-center justify-between mb-6 gap-3 flex-col md:flex-row">
                <div className="hidden md:block">
                    <div className="tech-stamp mb-1">Sous-traitance</div>
                    <h1 className="font-display font-bold uppercase text-2xl md:text-3xl tracking-tight flex items-center gap-2">
                        <HardHat className="w-6 h-6" /> Devis de travaux
                    </h1>
                    <p className="text-sm text-[#4b5d7a] mt-1">Le lieu, le problème du client et les travaux à faire, en un PDF clair pour le sous-traitant.</p>
                </div>
                <div className="flex gap-2">
                    <button onClick={load} className="btn-secondary !py-2 !px-3" title="Rafraîchir"><RefreshCw className="w-3.5 h-3.5" /></button>
                    <button onClick={openNew} className="btn-primary !py-2 !px-4 !text-xs" data-testid="wo-new">
                        <Plus className="w-3.5 h-3.5" /> Nouveau devis de travaux
                    </button>
                </div>
            </div>

            {notice && <div className="mb-4 p-3 border border-[#8ec79d] bg-[#e6f4ea] text-[#0b6b2f] text-sm" data-testid="wo-notice">{notice}</div>}
            {error && !open && <div className="mb-4 p-3 border border-red-400 bg-red-50 text-red-800 text-sm">{error}</div>}

            <div className="relative max-w-md mb-4">
                <Search className="w-4 h-4 text-[#97b0d0] absolute left-3 top-1/2 -translate-y-1/2" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher (numéro, sous-traitant, client, ville…)"
                    className={`${inputClass} pl-9`} data-testid="wo-search" />
            </div>

            <div className="border border-[#dde5f0] bg-white">
                <div className="hidden md:grid grid-cols-12 gap-3 px-4 py-3 border-b border-[#dde5f0] bg-[#f3f6fb] tech-stamp">
                    <div className="col-span-2">Numéro</div>
                    <div className="col-span-2">Sous-traitant</div>
                    <div className="col-span-3">Chantier</div>
                    <div className="col-span-1">Prévu</div>
                    <div className="col-span-2">Statut</div>
                    <div className="col-span-2 text-right">Actions</div>
                </div>
                {loading && <div className="p-8 text-center text-sm text-[#4b5d7a]"><Loader2 className="w-4 h-4 animate-spin inline" /> Chargement…</div>}
                {!loading && filtered.length === 0 && (
                    <div className="p-10 text-center text-sm text-[#4b5d7a]">
                        {query ? "Aucun résultat." : "Aucun devis de travaux. Cliquez sur « Nouveau devis de travaux » pour en créer un."}
                    </div>
                )}
                <ul>
                    {filtered.map((wo) => (
                        <li key={wo.id} className="border-b border-[#dde5f0] last:border-b-0 hover:bg-[#f9fbfe]">
                            <div className="grid grid-cols-1 md:grid-cols-12 gap-2 md:gap-3 px-4 py-3 items-center">
                                <div className="md:col-span-2 font-display font-bold text-sm">
                                    {wo.number}
                                    {wo.priority === "urgente" && <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-[#8a1f1f] text-white">URGENT</span>}
                                </div>
                                <div className="md:col-span-2 text-sm truncate">{wo.subcontractor_snapshot?.name || "—"}</div>
                                <div className="md:col-span-3 text-sm">
                                    <div className="truncate font-medium">{wo.site?.site_name || wo.site?.client_name || "—"}</div>
                                    <div className="text-xs text-[#4b5d7a] truncate">{[wo.site?.address, wo.site?.city].filter(Boolean).join(", ")}</div>
                                </div>
                                <div className="md:col-span-1 text-xs text-[#4b5d7a]">{wo.scheduled_date ? formatDate(wo.scheduled_date) : "À confirmer"}</div>
                                <div className="md:col-span-2">
                                    <select value={wo.status} onChange={(e) => quickStatus(wo, e.target.value)}
                                        data-testid={`wo-status-${wo.id}`}
                                        className={`tech-stamp text-[10px] px-2 py-1 border ${STATUS_STYLE[wo.status] || ""}`}>
                                        {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                                    </select>
                                    {wo.sent_to && <div className="text-[10px] text-[#4b5d7a] mt-1 truncate">Envoyé à {wo.sent_to}</div>}
                                </div>
                                <div className="md:col-span-2">{actions(wo)}</div>
                            </div>
                        </li>
                    ))}
                </ul>
            </div>

            <Modal open={open} onClose={() => setOpen(false)} wide testId="wo-modal"
                title={form.id ? `Devis de travaux ${form.number}` : "Nouveau devis de travaux"}
                footer={(
                    <>
                        {form.id && <button type="button" onClick={() => openPdf(form)} className="btn-secondary !py-2 !px-4 !text-xs"><Download className="w-3.5 h-3.5" /> PDF</button>}
                        <button type="button" onClick={() => setOpen(false)} className="btn-secondary !py-2 !px-4 !text-xs">Annuler</button>
                        <button type="button" onClick={() => save(false)} disabled={busy === "save"} className="btn-primary !py-2 !px-4 !text-xs" data-testid="wo-save">
                            {busy === "save" && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Enregistrer
                        </button>
                    </>
                )}>
                <div className="space-y-4">
                    {error && <div className="p-3 border border-red-400 bg-red-50 text-red-800 text-sm" data-testid="wo-error">{error}</div>}

                    <Section title="Sous-traitant" hint="Choisissez une fiche fournisseur ou tapez ses coordonnées.">
                        <div className="grid md:grid-cols-2 gap-3">
                            <Field label="Fiche fournisseur">
                                <select className={inputClass} value={form.subcontractor_id || ""} onChange={(e) => pickSupplier(e.target.value)} data-testid="wo-supplier">
                                    <option value="">— Choisir —</option>
                                    {suppliers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                            </Field>
                            <Field label="Nom" required><input className={inputClass} value={form.subcontractor_snapshot.name} onChange={(e) => setSub("name", e.target.value)} data-testid="wo-sub-name" /></Field>
                            <Field label="Personne-ressource"><input className={inputClass} value={form.subcontractor_snapshot.contact || ""} onChange={(e) => setSub("contact", e.target.value)} /></Field>
                            <Field label="Courriel"><input type="email" className={inputClass} value={form.subcontractor_snapshot.email || ""} onChange={(e) => setSub("email", e.target.value)} data-testid="wo-sub-email" /></Field>
                            <Field label="Téléphone"><input className={inputClass} value={form.subcontractor_snapshot.phone || ""} onChange={(e) => setSub("phone", e.target.value)} /></Field>
                        </div>
                    </Section>

                    <Section title="Lieu de l'intervention">
                        <div className="grid md:grid-cols-2 gap-3">
                            <Field label="Client (fiche)">
                                <select className={inputClass} value="" onChange={(e) => pickCustomer(e.target.value)} data-testid="wo-customer">
                                    <option value="">— Remplir depuis une fiche client —</option>
                                    {customers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                                </select>
                            </Field>
                            <Field label="Nom du client"><input className={inputClass} value={form.site.client_name} onChange={(e) => setSite("client_name", e.target.value)} data-testid="wo-client" /></Field>
                            <Field label="Nom du lieu / chantier"><input className={inputClass} placeholder="Ex. : Uniprix St-Martin — entrée principale" value={form.site.site_name} onChange={(e) => setSite("site_name", e.target.value)} /></Field>
                            <Field label="Adresse" required><input className={inputClass} value={form.site.address} onChange={(e) => setSite("address", e.target.value)} data-testid="wo-address" /></Field>
                            <Field label="Ville"><input className={inputClass} value={form.site.city} onChange={(e) => setSite("city", e.target.value)} data-testid="wo-city" /></Field>
                            <Field label="Code postal"><input className={inputClass} value={form.site.postal_code} onChange={(e) => setSite("postal_code", e.target.value)} /></Field>
                            <Field label="Contact sur place"><input className={inputClass} value={form.site.contact_name} onChange={(e) => setSite("contact_name", e.target.value)} /></Field>
                            <Field label="Téléphone sur place"><input className={inputClass} value={form.site.contact_phone} onChange={(e) => setSite("contact_phone", e.target.value)} /></Field>
                            <Field label="Porte / équipement visé" className="md:col-span-2"><input className={inputClass} placeholder="Ex. : Porte P1 — paire AT1000, anodisé noir" value={form.site.door_reference} onChange={(e) => setSite("door_reference", e.target.value)} /></Field>
                            <Field label="Accès, stationnement, horaires, clé, code…" className="md:col-span-2">
                                <textarea rows={2} className={inputClass} value={form.site.access_notes} onChange={(e) => setSite("access_notes", e.target.value)} />
                            </Field>
                        </div>
                    </Section>

                    <Section title="Problème rapporté par le client" hint="Dans les mots du client : ce qu'il voit, depuis quand, quand ça arrive.">
                        <textarea rows={3} className={inputClass} value={form.complaint} onChange={(e) => set("complaint", e.target.value)} data-testid="wo-complaint"
                            placeholder="Ex. : La porte ne se referme plus toute seule et claque quand il vente. Depuis lundi, elle ne se barre plus le soir." />
                        <Field label="Constat / cause probable (optionnel)">
                            <textarea rows={2} className={inputClass} value={form.diagnosis} onChange={(e) => set("diagnosis", e.target.value)} />
                        </Field>
                    </Section>

                    <Section title="Travaux à effectuer" hint="Une ligne par tâche ; elles deviennent des cases à cocher sur le PDF.">
                        {form.tasks.map((t, i) => (
                            <div key={t._key} className="flex gap-2 items-start">
                                <span className="pt-2.5 text-sm font-bold w-5 text-right">{i + 1}.</span>
                                <textarea rows={1} className={inputClass} value={t.description} onChange={(e) => updList("tasks", t._key, "description", e.target.value)} data-testid={`wo-task-${i}`} />
                                <div className="flex flex-col">
                                    <button type="button" onClick={() => move("tasks", t._key, -1)} className="p-1 text-[#4b5d7a]" title="Monter"><ArrowUp className="w-3.5 h-3.5" /></button>
                                    <button type="button" onClick={() => move("tasks", t._key, 1)} className="p-1 text-[#4b5d7a]" title="Descendre"><ArrowDown className="w-3.5 h-3.5" /></button>
                                </div>
                                <label className="flex items-center gap-1 text-xs pt-2.5 whitespace-nowrap" title="Cocher quand c'est fait">
                                    <input type="checkbox" checked={!!t.done} onChange={(e) => updList("tasks", t._key, "done", e.target.checked)} /> fait
                                </label>
                                <button type="button" onClick={() => removeFrom("tasks", t._key)} className="p-2 text-[#8a1f1f]" title="Retirer"><X className="w-4 h-4" /></button>
                            </div>
                        ))}
                        <button type="button" onClick={addTask} className="text-sm text-[#2f4f7f] inline-flex items-center gap-1" data-testid="wo-add-task"><Plus className="w-3.5 h-3.5" /> Ajouter une tâche</button>
                    </Section>

                    <Section title="Matériel">
                        {form.materials.map((m) => (
                            <div key={m._key} className="grid grid-cols-12 gap-2 items-center">
                                <input className={`${inputClass} col-span-12 md:col-span-7`} placeholder="Description" value={m.description} onChange={(e) => updList("materials", m._key, "description", e.target.value)} />
                                <input className={`${inputClass} col-span-3 md:col-span-1`} placeholder="Qté" value={m.qty} onChange={(e) => updList("materials", m._key, "qty", e.target.value)} />
                                <select className={`${inputClass} col-span-7 md:col-span-3`} value={m.supplied_by} onChange={(e) => updList("materials", m._key, "supplied_by", e.target.value)}>
                                    <option>Portech</option><option>Sous-traitant</option>
                                </select>
                                <button type="button" onClick={() => removeFrom("materials", m._key)} className="col-span-2 md:col-span-1 p-2 text-[#8a1f1f]" title="Retirer"><X className="w-4 h-4" /></button>
                            </div>
                        ))}
                        <button type="button" onClick={addMaterial} className="text-sm text-[#2f4f7f] inline-flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> Ajouter du matériel</button>
                    </Section>

                    <Section title="Photos" hint="Le problème, l'entrée, la quincaillerie actuelle… (8 max, réduites automatiquement). Elles sont imprimées sur le PDF.">
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            {(form.photos || []).map((p) => (
                                <div key={p.id} className="border border-[#dde5f0]">
                                    <img src={photoUrl(form.id, p.id)} alt={p.caption || "photo"} className="w-full h-28 object-cover" />
                                    <input className="w-full px-2 py-1 text-xs border-t border-[#dde5f0]" placeholder="Légende" defaultValue={p.caption}
                                        onBlur={(e) => e.target.value !== p.caption && captionPhoto(p.id, e.target.value)} />
                                    <button type="button" onClick={() => deletePhoto(p.id)} className="w-full text-xs text-[#8a1f1f] py-1 border-t border-[#dde5f0]">Retirer</button>
                                </div>
                            ))}
                        </div>
                        <label className="btn-secondary !py-2 !px-3 !text-xs inline-flex cursor-pointer">
                            {busy === "photo" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />}
                            Ajouter des photos
                            <input type="file" accept="image/*" multiple className="hidden" data-testid="wo-photo-input"
                                onChange={(e) => { const list = Array.from(e.target.files || []); e.target.value = ""; uploadPhotos(list); }} />
                        </label>
                        {!form.id && <div className="text-xs text-[#4b5d7a]">Le devis sera enregistré automatiquement avant l'ajout de la première photo.</div>}
                    </Section>

                    <Section title="Planification">
                        <div className="grid md:grid-cols-3 gap-3">
                            <Field label="Date prévue"><input type="date" className={inputClass} value={form.scheduled_date || ""} onChange={(e) => set("scheduled_date", e.target.value)} data-testid="wo-date" /></Field>
                            <Field label="Plage horaire"><input className={inputClass} placeholder="Ex. : 7 h à 9 h" value={form.scheduled_window} onChange={(e) => set("scheduled_window", e.target.value)} /></Field>
                            <Field label="Durée estimée"><input className={inputClass} placeholder="Ex. : 2 à 3 h" value={form.estimated_duration} onChange={(e) => set("estimated_duration", e.target.value)} /></Field>
                            <Field label="Priorité">
                                <select className={inputClass} value={form.priority} onChange={(e) => set("priority", e.target.value)}>
                                    <option value="normale">Normale</option><option value="urgente">Urgente</option>
                                </select>
                            </Field>
                            <Field label="Statut">
                                <select className={inputClass} value={form.status} onChange={(e) => set("status", e.target.value)}>
                                    {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                                </select>
                            </Field>
                            <Field label="Job liée">
                                <select className={inputClass} value={form.job_id || ""} onChange={(e) => pickJob(e.target.value)}>
                                    <option value="">— Aucune —</option>
                                    {jobs.map((j) => <option key={j.id} value={j.id}>{j.job_number} · {j.title}</option>)}
                                </select>
                            </Field>
                            <Field label="Réf. du client (bon de commande…)"><input className={inputClass} value={form.client_reference} onChange={(e) => set("client_reference", e.target.value)} /></Field>
                        </div>
                    </Section>

                    <Section title="Rémunération du sous-traitant">
                        <div className="grid md:grid-cols-3 gap-3">
                            <Field label="Mode">
                                <select className={inputClass} value={form.pay_mode} onChange={(e) => set("pay_mode", e.target.value)} data-testid="wo-pay-mode">
                                    <option value="à confirmer">À confirmer</option><option value="forfait">Forfait</option><option value="taux horaire">Taux horaire</option>
                                </select>
                            </Field>
                            {form.pay_mode !== "à confirmer" && (
                                <Field label={form.pay_mode === "forfait" ? "Montant du forfait ($)" : "Taux ($/h)"}>
                                    <input type="number" min="0" step="0.01" className={inputClass} value={form.pay_amount} onChange={(e) => set("pay_amount", e.target.value)} data-testid="wo-pay-amount" />
                                </Field>
                            )}
                            {form.pay_mode === "taux horaire" && (
                                <Field label="Heures max sans autorisation"><input type="number" min="0" step="0.5" className={inputClass} value={form.pay_max_hours} onChange={(e) => set("pay_max_hours", e.target.value)} /></Field>
                            )}
                            <Field label="Conditions" className="md:col-span-3"><input className={inputClass} placeholder="Ex. : payable 30 jours après réception de la facture et des photos" value={form.pay_notes} onChange={(e) => set("pay_notes", e.target.value)} /></Field>
                            <label className="flex items-center gap-2 text-sm md:col-span-3">
                                <input type="checkbox" checked={form.show_pay_on_pdf} onChange={(e) => set("show_pay_on_pdf", e.target.checked)} /> Afficher la rémunération sur le PDF
                            </label>
                        </div>
                        {form.pay_mode === "forfait" && Number(form.pay_amount) > 0 && (
                            <div className="text-xs text-[#4b5d7a]">Forfait : {formatCurrency(Number(form.pay_amount))} (taxes en sus)</div>
                        )}
                    </Section>

                    <Section title="Consignes au sous-traitant" hint="Une consigne par ligne.">
                        <textarea rows={5} className={inputClass} value={form.instructions} onChange={(e) => set("instructions", e.target.value)} />
                    </Section>

                    <Section title="Notes internes" hint="Jamais imprimées sur le PDF (ex. prix facturé au client).">
                        <textarea rows={2} className={inputClass} value={form.internal_notes} onChange={(e) => set("internal_notes", e.target.value)} />
                    </Section>
                </div>
            </Modal>
        </div>
    );
};
