import { useCallback, useEffect, useState } from "react";
import { Plus, Trash2, Wallet, FileMinus, Ban, Loader2 } from "lucide-react";
import { Modal, Field, inputClass } from "./Modal";
import { StatusBadge } from "./StatusBadge";
import { formatCurrency, formatDate, localISO } from "../utils";

const PAYMENT_MODES = ["Transfert", "Chèque", "Comptant", "Carte", "Autre"];
const today = () => localISO();

/**
 * Suivi des paiements d'une facture : paiements partiels, notes de crédit et
 * annulation (motif obligatoire). Le statut est recalculé côté serveur.
 */
export const PaymentsModal = ({ open, invoice, onClose, http, onChanged, numberPrefix = "FAC" }) => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [summary, setSummary] = useState(null);
    const [payments, setPayments] = useState([]);
    const [credits, setCredits] = useState([]);
    const [busy, setBusy] = useState(false);

    // Formulaire paiement
    const [pAmount, setPAmount] = useState("");
    const [pDate, setPDate] = useState(today());
    const [pMode, setPMode] = useState("Transfert");
    const [pRef, setPRef] = useState("");

    // Formulaire note de crédit
    const [cAmount, setCAmount] = useState("");
    const [cDate, setCDate] = useState(today());
    const [cReason, setCReason] = useState("");

    // Annulation
    const [showCancel, setShowCancel] = useState(false);
    const [cancelReason, setCancelReason] = useState("");

    const invoiceId = invoice?.id;
    const label = invoice ? `${numberPrefix}-${String(invoice.number).padStart(4, "0")}` : "";

    const load = useCallback(async () => {
        if (!invoiceId) return;
        setLoading(true); setError("");
        try {
            const { data } = await http.get(`/admin/invoices/${invoiceId}/payments`);
            setSummary(data);
            setPayments(data.payments || []);
            setCredits(data.credit_notes || []);
        } catch (e) {
            setError(e?.response?.data?.detail || "Erreur de chargement");
        } finally {
            setLoading(false);
        }
    }, [http, invoiceId]);

    useEffect(() => {
        if (open) {
            setError(""); setShowCancel(false); setCancelReason("");
            setPAmount(""); setPDate(today()); setPMode("Transfert"); setPRef("");
            setCAmount(""); setCDate(today()); setCReason("");
            load();
        }
    }, [open, load]);

    const refreshAll = async () => { await load(); onChanged?.(); };

    const addPayment = async () => {
        const amt = Number(pAmount);
        if (!amt || amt <= 0) { setError("Montant du paiement invalide."); return; }
        setBusy(true); setError("");
        try {
            await http.post(`/admin/invoices/${invoiceId}/payments`, {
                amount: amt, date: pDate, mode: pMode, reference: pRef,
            });
            setPAmount(""); setPRef("");
            await refreshAll();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de l'enregistrement du paiement.");
        } finally { setBusy(false); }
    };

    const deletePayment = async (pid) => {
        if (!window.confirm("Supprimer ce paiement ?")) return;
        setBusy(true); setError("");
        try {
            await http.delete(`/admin/invoices/${invoiceId}/payments/${pid}`);
            await refreshAll();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de la suppression.");
        } finally { setBusy(false); }
    };

    const addCredit = async () => {
        const amt = Number(cAmount);
        if (!amt || amt <= 0) { setError("Montant de la note de crédit invalide."); return; }
        if (!cReason.trim()) { setError("Un motif est obligatoire pour une note de crédit."); return; }
        setBusy(true); setError("");
        try {
            await http.post(`/admin/invoices/${invoiceId}/credit-notes`, {
                amount: amt, date: cDate, reason: cReason.trim(),
            });
            setCAmount(""); setCReason("");
            await refreshAll();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de l'enregistrement de la note de crédit.");
        } finally { setBusy(false); }
    };

    const cancelInvoice = async () => {
        if (!cancelReason.trim()) { setError("Un motif est obligatoire pour annuler la facture."); return; }
        setBusy(true); setError("");
        try {
            await http.post(`/admin/invoices/${invoiceId}/cancel`, { reason: cancelReason.trim() });
            await refreshAll();
            onClose?.();
        } catch (e) {
            setError(e?.response?.data?.detail || "Échec de l'annulation.");
        } finally { setBusy(false); }
    };

    const cancelled = (summary?.status || invoice?.status) === "annulée";
    const draftLike = ["brouillon", "en attente d'approbation"].includes(invoice?.status);

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={`Paiements · ${label}`}
            testId="payments-modal"
            wide
            footer={
                <button onClick={onClose} className="btn-secondary !py-2 !px-4 !text-xs" data-testid="payments-close-btn">
                    Fermer
                </button>
            }
        >
            {loading && (
                <div className="flex items-center gap-2 text-sm text-[#4b5d7a] py-6">
                    <Loader2 className="w-4 h-4 animate-spin" /> Chargement…
                </div>
            )}

            {error && (
                <div className="mb-4 p-3 border border-red-400 bg-red-50 text-red-800 text-sm" data-testid="payments-error">
                    {error}
                </div>
            )}

            {!loading && summary && (
                <div className="space-y-6">
                    {/* Résumé financier */}
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="payments-summary">
                        <SummaryCell label="Total" value={formatCurrency(summary.total)} />
                        <SummaryCell label="Payé" value={formatCurrency(summary.paid_total)} tone="text-[#0b6b2f]" />
                        <SummaryCell label="Notes de crédit" value={formatCurrency(summary.credit_total)} tone="text-[#1d4ed8]" />
                        <SummaryCell label="Solde dû" value={formatCurrency(summary.balance)} tone="text-[#9a3b00]" testid="payments-balance" />
                        <div className="border border-[#dde5f0] bg-[#f3f6fb] p-3 flex flex-col justify-between">
                            <span className="tech-stamp mb-1">Statut</span>
                            <StatusBadge status={summary.status} />
                        </div>
                    </div>

                    {cancelled && (
                        <div className="p-3 border border-[#e8a5a5] bg-[#fbe8e8] text-[#8a1f1f] text-sm">
                            Facture annulée — aucune opération possible.
                        </div>
                    )}

                    {/* ── PAIEMENTS ── */}
                    <section>
                        <h4 className="font-display font-bold uppercase text-sm tracking-tight flex items-center gap-2 mb-3">
                            <Wallet className="w-4 h-4 text-[#2f4f7f]" /> Paiements reçus
                        </h4>
                        {payments.length === 0 ? (
                            <p className="text-xs text-[#4b5d7a] mb-3">Aucun paiement enregistré.</p>
                        ) : (
                            <ul className="border border-[#dde5f0] divide-y divide-[#dde5f0] mb-3" data-testid="payments-list">
                                {payments.map((p) => (
                                    <li key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
                                        <div className="min-w-0">
                                            <span className="font-display font-bold">{formatCurrency(p.amount)}</span>
                                            <span className="text-[#4b5d7a]"> · {p.mode}{p.reference ? ` · ${p.reference}` : ""}</span>
                                            <span className="text-xs text-[#97b0d0] block">{formatDate(p.date)}</span>
                                        </div>
                                        {!cancelled && (
                                            <button
                                                onClick={() => deletePayment(p.id)}
                                                disabled={busy}
                                                title="Supprimer ce paiement"
                                                data-testid={`payment-delete-${p.id}`}
                                                className="p-2 border border-[#dde5f0] hover:bg-red-50 text-red-600 disabled:opacity-40"
                                            >
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </button>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}
                        {!cancelled && !draftLike && (
                            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end bg-[#f3f6fb] border border-[#dde5f0] p-3">
                                <Field label="Montant" required className="col-span-1">
                                    <input type="number" step="0.01" min="0" value={pAmount}
                                        onChange={(e) => setPAmount(e.target.value)} className={inputClass}
                                        placeholder="0,00" data-testid="payment-amount" />
                                </Field>
                                <Field label="Date" className="col-span-1">
                                    <input type="date" value={pDate} onChange={(e) => setPDate(e.target.value)}
                                        className={inputClass} data-testid="payment-date" />
                                </Field>
                                <Field label="Mode" className="col-span-1">
                                    <select value={pMode} onChange={(e) => setPMode(e.target.value)}
                                        className={inputClass} data-testid="payment-mode">
                                        {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
                                    </select>
                                </Field>
                                <Field label="Référence" className="col-span-1">
                                    <input type="text" value={pRef} onChange={(e) => setPRef(e.target.value)}
                                        className={inputClass} placeholder="No chèque…" data-testid="payment-reference" />
                                </Field>
                                <button onClick={addPayment} disabled={busy}
                                    data-testid="payment-add-btn"
                                    className="btn-primary !py-2.5 !px-4 !text-xs col-span-1 disabled:opacity-40">
                                    <Plus className="w-3.5 h-3.5" /> Ajouter
                                </button>
                            </div>
                        )}
                    </section>

                    {/* ── NOTES DE CRÉDIT ── */}
                    <section>
                        <h4 className="font-display font-bold uppercase text-sm tracking-tight flex items-center gap-2 mb-3">
                            <FileMinus className="w-4 h-4 text-[#1d4ed8]" /> Notes de crédit
                        </h4>
                        {credits.length === 0 ? (
                            <p className="text-xs text-[#4b5d7a] mb-3">Aucune note de crédit.</p>
                        ) : (
                            <ul className="border border-[#dde5f0] divide-y divide-[#dde5f0] mb-3" data-testid="credit-notes-list">
                                {credits.map((c) => (
                                    <li key={c.id} className="px-3 py-2 text-sm">
                                        <span className="font-display font-bold">{formatCurrency(c.amount)}</span>
                                        <span className="text-xs text-[#97b0d0]"> · {formatDate(c.date)}</span>
                                        <span className="text-[#4b5d7a] block text-xs">Motif : {c.reason}</span>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {!cancelled && !draftLike && (
                            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end bg-[#f3f6fb] border border-[#dde5f0] p-3">
                                <Field label="Montant" required className="col-span-1">
                                    <input type="number" step="0.01" min="0" value={cAmount}
                                        onChange={(e) => setCAmount(e.target.value)} className={inputClass}
                                        placeholder="0,00" data-testid="credit-amount" />
                                </Field>
                                <Field label="Date" className="col-span-1">
                                    <input type="date" value={cDate} onChange={(e) => setCDate(e.target.value)}
                                        className={inputClass} data-testid="credit-date" />
                                </Field>
                                <Field label="Motif" required className="col-span-2">
                                    <input type="text" value={cReason} onChange={(e) => setCReason(e.target.value)}
                                        className={inputClass} placeholder="Correction, rabais…" data-testid="credit-reason" />
                                </Field>
                                <button onClick={addCredit} disabled={busy}
                                    data-testid="credit-add-btn"
                                    className="btn-primary !py-2.5 !px-4 !text-xs col-span-1 disabled:opacity-40">
                                    <Plus className="w-3.5 h-3.5" /> Ajouter
                                </button>
                            </div>
                        )}
                    </section>

                    {/* ── ANNULATION (propriétaire) ── */}
                    {!cancelled && !draftLike && (
                        <section className="border-t border-[#dde5f0] pt-4">
                            {!showCancel ? (
                                <button onClick={() => setShowCancel(true)}
                                    data-testid="cancel-invoice-open-btn"
                                    className="inline-flex items-center gap-2 text-sm text-red-600 border border-[#e8a5a5] hover:bg-red-50 px-3 py-2">
                                    <Ban className="w-4 h-4" /> Annuler cette facture
                                </button>
                            ) : (
                                <div className="bg-[#fbe8e8] border border-[#e8a5a5] p-3 space-y-3">
                                    <p className="text-sm text-[#8a1f1f]">
                                        L'annulation est définitive (la facture n'est pas supprimée). Un motif est obligatoire.
                                    </p>
                                    <Field label="Motif de l'annulation" required>
                                        <input type="text" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)}
                                            className={inputClass} placeholder="Erreur de facturation, doublon…"
                                            data-testid="cancel-reason" />
                                    </Field>
                                    <div className="flex gap-2 justify-end">
                                        <button onClick={() => setShowCancel(false)} disabled={busy}
                                            className="btn-secondary !py-2 !px-4 !text-xs">Retour</button>
                                        <button onClick={cancelInvoice} disabled={busy}
                                            data-testid="cancel-invoice-confirm-btn"
                                            className="!py-2 !px-4 !text-xs inline-flex items-center gap-2 bg-red-600 text-white hover:bg-red-700 disabled:opacity-40">
                                            <Ban className="w-3.5 h-3.5" /> Confirmer l'annulation
                                        </button>
                                    </div>
                                </div>
                            )}
                        </section>
                    )}
                </div>
            )}
        </Modal>
    );
};

const SummaryCell = ({ label, value, tone = "text-[#0c182b]", testid }) => (
    <div className="border border-[#dde5f0] bg-white p-3" data-testid={testid}>
        <span className="tech-stamp block mb-1">{label}</span>
        <span className={`font-display font-bold text-lg ${tone}`}>{value}</span>
    </div>
);
