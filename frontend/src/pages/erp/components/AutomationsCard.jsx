import { useCallback, useEffect, useState } from "react";
import { BellRing, ChevronDown, ChevronUp, Loader2, Send, AlertTriangle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { formatCurrency } from "../utils";

/**
 * Envois automatiques (relances de factures, états de compte mensuels, suivis
 * de soumissions) : interrupteurs visibles + aperçu des relances qui partiront
 * au prochain passage de 8 h.
 */
export const AutomationsCard = () => {
    const { http } = useAuth();
    const [items, setItems] = useState([]);
    const [preview, setPreview] = useState(null);
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState("");
    const [msg, setMsg] = useState("");

    const load = useCallback(async () => {
        try {
            const [a, p] = await Promise.all([
                http.get("/admin/automations"),
                http.get("/admin/reminders/preview"),
            ]);
            setItems(a.data.automations || []);
            setPreview(p.data);
        } catch (e) {
            setMsg(e?.response?.data?.detail || "Impossible de charger les envois automatiques.");
        }
    }, [http]);

    useEffect(() => { load(); }, [load]);

    const toggle = async (it) => {
        setBusy(it.key); setMsg("");
        try {
            await http.put(`/admin/automations/${it.key}`, { enabled: !it.enabled });
            await load();
        } catch (e) {
            setMsg(e?.response?.data?.detail || "Échec de la mise à jour.");
        } finally { setBusy(""); }
    };

    const runNow = async () => {
        const n = preview?.count || 0;
        if (!n) return;
        if (!window.confirm(`Envoyer maintenant ${n} relance(s) par courriel aux clients ?`)) return;
        setBusy("run"); setMsg("");
        try {
            const { data } = await http.post("/admin/reminders/run-now", { confirm: "EXECUTER" });
            setMsg(`${data.sent} relance(s) envoyée(s).`);
            await load();
        } catch (e) {
            setMsg(e?.response?.data?.detail || "Échec de l'envoi.");
        } finally { setBusy(""); }
    };

    const reminders = items.find((i) => i.key === "invoice_reminders");
    const pending = preview?.invoices || [];
    const noEmail = pending.filter((i) => !i.has_email);
    const activeCount = items.filter((i) => i.active).length;

    return (
        <div className="border border-[#dde5f0] bg-white mb-6" data-testid="automations-card">
            <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[#f3f6fb]"
                data-testid="automations-toggle-open"
            >
                <span className="flex items-center gap-2 min-w-0">
                    <BellRing className="w-4 h-4 text-[#2f4f7f] shrink-0" />
                    <span className="font-display font-bold text-sm uppercase tracking-wide">Envois automatiques</span>
                    <span className="text-xs text-[#4b5d7a] truncate">
                        {activeCount}/{items.length || 3} actif(s)
                        {reminders && (reminders.active
                            ? ` · ${pending.length} relance(s) prévue(s) au prochain passage de 8 h`
                            : " · relances de factures désactivées")}
                    </span>
                </span>
                {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>

            {open && (
                <div className="border-t border-[#dde5f0] p-4 space-y-4">
                    <ul className="space-y-3">
                        {items.map((it) => (
                            <li key={it.key} className="flex items-start justify-between gap-4">
                                <div className="min-w-0">
                                    <div className="text-sm font-semibold text-[#0c182b]">{it.label}</div>
                                    <div className="text-xs text-[#4b5d7a]">{it.description}</div>
                                    {it.server_note && <div className="text-xs text-[#9a3b00] mt-1">{it.server_note}</div>}
                                </div>
                                <button
                                    type="button"
                                    role="switch"
                                    aria-checked={it.enabled}
                                    disabled={busy === it.key}
                                    onClick={() => toggle(it)}
                                    data-testid={`automation-switch-${it.key}`}
                                    className={`relative shrink-0 w-11 h-6 rounded-full transition-colors ${it.enabled ? "bg-[#0b6b2f]" : "bg-[#c5d4e7]"}`}
                                    title={it.enabled ? "Activé — cliquer pour désactiver" : "Désactivé — cliquer pour activer"}
                                >
                                    <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${it.enabled ? "translate-x-5" : ""}`} />
                                </button>
                            </li>
                        ))}
                    </ul>

                    <div className="border-t border-[#dde5f0] pt-4">
                        <div className="flex items-center justify-between gap-3 mb-2 flex-wrap">
                            <div className="tech-stamp">Relances prévues au prochain passage (8 h)</div>
                            <button
                                type="button"
                                onClick={runNow}
                                disabled={!reminders?.active || !pending.length || busy === "run"}
                                className="btn-secondary !py-1.5 !px-3 !text-xs disabled:opacity-40"
                                data-testid="automations-run-now"
                            >
                                {busy === "run" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                                Envoyer maintenant
                            </button>
                        </div>
                        {pending.length === 0 ? (
                            <div className="text-xs text-[#4b5d7a]">Aucune facture à relancer pour l'instant.</div>
                        ) : (
                            <table className="w-full text-xs">
                                <thead className="text-[#4b5d7a] text-left">
                                    <tr><th className="py-1">Facture</th><th>Client</th><th>Retard</th><th>Palier</th><th className="text-right">Solde</th></tr>
                                </thead>
                                <tbody>
                                    {pending.map((i) => (
                                        <tr key={i.number} className="border-t border-[#eef2f8]">
                                            <td className="py-1.5 font-semibold">{i.number}</td>
                                            <td>
                                                {i.customer || "—"}
                                                {!i.has_email && <span className="ml-2 text-[#9a3b00]">(aucun courriel)</span>}
                                            </td>
                                            <td>{i.days_past_due} j</td>
                                            <td>{i.palier}</td>
                                            <td className="text-right">{formatCurrency(i.balance)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                        {noEmail.length > 0 && (
                            <div className="mt-2 flex items-start gap-2 text-xs text-[#9a3b00]">
                                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                                {noEmail.length} facture(s) ne peuvent pas être relancées : le client n'a pas de courriel.
                                Ajoutez-le dans la fiche client puis sur la facture.
                            </div>
                        )}
                    </div>
                    {msg && <div className="text-xs text-[#2f4f7f]" data-testid="automations-msg">{msg}</div>}
                </div>
            )}
        </div>
    );
};
