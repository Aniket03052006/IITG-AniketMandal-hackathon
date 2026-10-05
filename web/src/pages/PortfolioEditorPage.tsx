import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useParsePortfolio, usePortfolio, usePortfolioMutations, useValidatePortfolio } from "../api/hooks";
import type { ResolvedPortfolio } from "../api/types";
import { HoldingsPreview } from "../components/portfolio/HoldingsPreview";
import { ArrowLeft, Plus, Spinner } from "../components/icons";
import { StateNotice } from "../components/StateNotice";
import { Tabs } from "../components/Tabs";
import { ErrorState, Loading, PageHeader } from "../components/ui";
import { setActivePortfolio } from "../lib/portfolio";
import { CURRENCIES, emptyForm, emptyRow, type Form, fromInput, hasContent, QUICK_EXAMPLE, QUICK_EXAMPLE_QTY, type Row, toInput } from "../lib/portfolioForm";

const CLASSES = [
  ["", "Auto"],
  ["EQUITY", "Equity"],
  ["BOND", "Bond"],
  ["CASH", "Cash"],
  ["OTHER", "Other (not stressed)"],
] as const;

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block min-w-0">
      <span className="eyebrow mb-1.5 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

function RowEditor({ row, i, mode, onChange, onRemove, only }: { row: Row; i: number; mode: Form["mode"]; onChange: (r: Row) => void; onRemove: () => void; only: boolean }) {
  const set = (k: keyof Row) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...row, [k]: e.target.value });
  return (
    <li className="holding" aria-label={`Holding ${i + 1}`}>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
        <Field label="Ticker">
          <input className="field uppercase" value={row.ticker} onChange={set("ticker")} placeholder="AAPL, TLT, CASH" aria-label={`Ticker ${i + 1}`} autoCapitalize="characters" />
        </Field>
        {mode === "WEIGHT" ? (
          <Field label="Weight %">
            <input className="field" inputMode="decimal" value={row.weight} onChange={set("weight")} placeholder="20" aria-label={`Weight ${i + 1}`} />
          </Field>
        ) : (
          <>
            <Field label="Quantity">
              <input className="field" inputMode="decimal" value={row.quantity} onChange={set("quantity")} placeholder="100" aria-label={`Quantity ${i + 1}`} />
            </Field>
            <Field label="Price">
              <input className="field" inputMode="decimal" value={row.price} onChange={set("price")} placeholder="190.00" aria-label={`Price ${i + 1}`} />
            </Field>
          </>
        )}
        {mode === "WEIGHT" && <div className="hidden sm:block" />}
        <button type="button" className="btn btn-ghost" onClick={onRemove} disabled={only} aria-label={`Remove holding ${i + 1}`}>
          Remove
        </button>
      </div>
      <details className="disclosure mt-2">
        <summary>More about this holding (class, sector, region, currency, cost, beta, duration)</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Name">
            <input className="field" value={row.name} onChange={set("name")} />
          </Field>
          <Field label="Asset class">
            <select className="field" value={row.assetClass} onChange={set("assetClass")}>
              {CLASSES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Sector" hint="Financials, Technology, Energy, Healthcare, Industrials, Consumer">
            <input className="field" value={row.sector} onChange={set("sector")} />
          </Field>
          <Field label="Region" hint="US, GB, EU, CN, JP, IN, MIDEAST">
            <input className="field" value={row.region} onChange={set("region")} />
          </Field>
          <Field label="Currency">
            <input className="field uppercase" value={row.currency} onChange={set("currency")} maxLength={3} placeholder="same as portfolio" />
          </Field>
          <Field label="Cost per unit" hint="Only for unrealised gain; never used by the stress">
            <input className="field" inputMode="decimal" value={row.cost} onChange={set("cost")} />
          </Field>
          <Field label="Beta (equity)" hint="Overrides the looked-up beta">
            <input className="field" inputMode="decimal" value={row.beta} onChange={set("beta")} />
          </Field>
          <Field label="Duration, years (bond)" hint="Required for a bond with no reference">
            <input className="field" inputMode="decimal" value={row.duration} onChange={set("duration")} />
          </Field>
        </div>
      </details>
    </li>
  );
}

/** Create or edit a personal portfolio: type or paste quickly, or fill the detailed rows; the server resolves it live and says what it assumed. */
export function PortfolioEditorPage() {
  const { id } = useParams();
  const editing = !!id && id !== "new";
  const nav = useNavigate();
  const stored = usePortfolio(editing ? id : undefined);
  const [form, setForm] = useState<Form>(emptyForm);
  const [tab, setTab] = useState<"quick" | "detailed">("quick");
  const [quick, setQuick] = useState("");
  const [useNow, setUseNow] = useState(true);
  const [resolved, setResolved] = useState<ResolvedPortfolio | null>(null);
  const validate = useValidatePortfolio();
  const parse = useParsePortfolio();
  const m = usePortfolioMutations();
  const loaded = useRef(false);

  useEffect(() => {
    if (editing && stored.data?.stored && !loaded.current) {
      loaded.current = true;
      setForm(fromInput(stored.data.stored));
      setTab("detailed");
    }
  }, [editing, stored.data]);

  // live check (debounced): the same resolver that decides whether it can be saved
  useEffect(() => {
    if (!hasContent(form)) {
      setResolved(null);
      return;
    }
    const t = setTimeout(() => validate.mutate(toInput(form), { onSuccess: setResolved }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form]);

  const setRow = (i: number, r: Row) => setForm((f) => ({ ...f, rows: f.rows.map((x, j) => (j === i ? r : x)) }));
  const readQuick = () =>
    parse.mutate(
      { text: quick, base_currency: form.currency, name: form.name },
      {
        onSuccess: (res) => {
          if (res.draft) {
            setForm({ ...fromInput(res.draft), name: form.name, currency: form.currency });
            setTab("detailed");
          }
        },
      },
    );

  const save = () => {
    const body = toInput(form);
    const done = (pid: string) => {
      if (useNow) setActivePortfolio(pid);
      nav("/portfolios");
    };
    if (editing && id) m.update.mutate({ id, body }, { onSuccess: (v) => done(v.id) });
    else m.create.mutate(body, { onSuccess: (v) => done(v.id) });
  };
  const saving = m.create.isPending || m.update.isPending;
  const saveError = (m.create.error ?? m.update.error) as Error | null;

  if (editing && stored.isLoading) return <Loading label="Loading portfolio" />;
  if (editing && stored.error) return <ErrorState error={stored.error} retry={() => stored.refetch()} />;

  return (
    <>
      <Link to="/portfolios" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft size={14} /> Portfolios
      </Link>
      <PageHeader
        title={editing ? "Edit portfolio" : "Create a portfolio"}
        sub="Optional. Enter what you hold; EventShock will say what it looked up and what it had to assume. Your holdings stay on this machine."
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Field label="Name">
          <input className="field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Portfolio name" />
        </Field>
        <Field label="Currency">
          <select className="field" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} aria-label="Portfolio currency">
            {CURRENCIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Field>
        <Field label="Enter holdings as">
          <select className="field" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as Form["mode"] })} aria-label="Entry mode">
            <option value="WEIGHT">Weights (% of portfolio)</option>
            <option value="QUANTITY">Quantity × price</option>
          </select>
        </Field>
      </div>

      <Tabs
        label="How to enter holdings"
        active={tab}
        onChange={(t) => setTab(t as "quick" | "detailed")}
        tabs={[
          { id: "quick", label: "Quick entry" },
          { id: "detailed", label: "Detailed" },
        ]}
      >
        {tab === "quick" ? (
          <div className="max-w-[44rem]">
            <p className="mb-2 text-sm text-ink-2">One holding per line: a ticker and a weight (<code>AAPL 20%</code>) or a quantity and price (<code>AAPL 100 @ 190</code>). Cash is just <code>Cash 25%</code>.</p>
            <textarea className="field min-h-40 font-mono" value={quick} onChange={(e) => setQuick(e.target.value)} placeholder={QUICK_EXAMPLE} aria-label="Holdings, one per line" />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" className="btn btn-primary" onClick={readQuick} disabled={!quick.trim() || parse.isPending}>
                {parse.isPending ? <Spinner size={14} /> : null} Read these holdings
              </button>
              <button type="button" className="chip" onClick={() => setQuick(QUICK_EXAMPLE)}>
                Example: weights
              </button>
              <button type="button" className="chip" onClick={() => setQuick(QUICK_EXAMPLE_QTY)}>
                Example: quantities
              </button>
            </div>
            {parse.error && <div className="mt-3"><ErrorState error={parse.error} /></div>}
            {parse.data && !parse.data.draft && (
              <div className="mt-3">
                <StateNotice
                  tone="warn"
                  what="Some lines could not be read"
                  why={<ul className="list-disc space-y-1 pl-4">{parse.data.issues.map((i) => <li key={i.message}>{i.message}</li>)}</ul>}
                />
              </div>
            )}
          </div>
        ) : (
          <div>
            {form.mode === "WEIGHT" && (
              <div className="mb-4 grid max-w-[40rem] gap-4 sm:grid-cols-2">
                <Field label={`Total value (${form.currency})`} hint="Weights are applied to this. Leave empty to use 1,000,000.">
                  <input className="field" inputMode="decimal" value={form.totalValue} onChange={(e) => setForm({ ...form, totalValue: e.target.value })} aria-label="Total value" />
                </Field>
                <label className="flex items-start gap-2 self-end pb-2 text-sm text-ink-2">
                  <input type="checkbox" className="mt-1" checked={form.remainderAsCash} onChange={(e) => setForm({ ...form, remainderAsCash: e.target.checked })} />
                  <span>If the weights add up to less than 100%, hold the rest as cash</span>
                </label>
              </div>
            )}
            <ol className="space-y-3">
              {form.rows.map((r, i) => (
                <RowEditor key={i} row={r} i={i} mode={form.mode} only={form.rows.length === 1} onChange={(x) => setRow(i, x)} onRemove={() => setForm({ ...form, rows: form.rows.filter((_, j) => j !== i) })} />
              ))}
            </ol>
            <button type="button" className="btn mt-3" onClick={() => setForm({ ...form, rows: [...form.rows, emptyRow()] })}>
              <Plus size={14} /> Add a holding
            </button>
          </div>
        )}
      </Tabs>

      <section className="mt-10" aria-label="What EventShock understood" aria-live="polite">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">What EventShock understood</h2>
          {validate.isPending && <Spinner size={14} />}
        </div>
        {resolved ? <HoldingsPreview r={resolved} /> : <p className="text-sm text-muted">Add a holding to see it resolved here.</p>}
      </section>

      <div className="mt-8 flex flex-wrap items-center gap-4 border-t border-rule pt-5">
        <button type="button" className="btn btn-primary" onClick={save} disabled={!resolved?.ok || saving} data-loading={saving}>
          {saving ? <Spinner size={14} /> : null} {editing ? "Save changes" : "Save portfolio"}
        </button>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" checked={useNow} onChange={(e) => setUseNow(e.target.checked)} />
          Use it now (you can go back to the default portfolio at any time)
        </label>
        <Link to="/portfolios" className="btn btn-ghost">
          Cancel
        </Link>
      </div>
      {saveError && <div className="mt-4"><ErrorState error={saveError} /></div>}
    </>
  );
}
