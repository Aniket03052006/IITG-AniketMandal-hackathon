import { useImpactModel } from "../../api/hooks";
import type { RiskSignal, SignalContext } from "../../api/types";
import { ShieldGlyph } from "../icons";
import { StateNotice } from "../StateNotice";
import { Chapter } from "./Chapter";
import { ComparablesPlot } from "./ComparablesPlot";
import { Coverage } from "./Coverage";
import { KnowledgeTimeline } from "./KnowledgeTimeline";
import { useOpenDrawer } from "../Drawer";

/** Chapter 4: what supports the estimate (comparable history, coverage) and what EventShock knew at each moment. */
export function EvidenceChapter({
  s,
  ctx,
  ctxLoading,
  ctxError,
  asOf,
  label,
}: {
  s: RiskSignal;
  ctx: SignalContext | undefined;
  ctxLoading: boolean;
  ctxError: Error | null;
  asOf: string;
  label: (c: string) => string;
}) {
  const audit = s.provenance?.impact;
  const modelled = !!audit && s.impact?.comparable_events != null;
  const { data: card } = useImpactModel(modelled);
  const scope = audit ? card?.scopes.find((x) => x.scope === audit.scope) : undefined;
  const [, setOpen] = useOpenDrawer();
  return (
    <Chapter
      id="evidence"
      eyebrow="Evidence"
      title="What supports it, and what was known when"
      lede="History that resembles this estimate, who else reported the story, and a timeline you can move through to see exactly what EventShock knew."
    >
      <div className="evidence-grid">
        <div>
          {modelled && s.impact ? (
            <ComparablesPlot impact={s.impact} baseRate={scope?.calibration?.base_rate_extreme} />
          ) : (
            <StateNotice
              tone="info"
              what="No comparable events for this score"
              why="Comparable events are statistics of the trained model's own history, so a score set by the placeholder rule has none. EventShock does not invent a comparison."
            />
          )}
        </div>
        <Coverage s={s} asOf={asOf} />
      </div>

      <div className="mt-10">
        <h3 className="text-lg font-semibold">What did EventShock know at this moment?</h3>
        <p className="mb-5 mt-1 max-w-[70ch] text-sm text-muted">
          The model reads the report and only what was published before it. Move the slider to watch later facts arrive: they are shown, but never fed back into the estimate.
        </p>
        <KnowledgeTimeline s={s} ctx={ctx} loading={ctxLoading} error={ctxError} label={label} />
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-rule pt-5">
        <button type="button" className="btn btn-ghost" onClick={() => setOpen("audit")} aria-haspopup="dialog">
          <ShieldGlyph size={14} /> Audit trail
        </button>
        {s.document.url?.startsWith("https://") && s.data_origin !== "DEMO_FIXTURE" && (
          <a className="btn btn-ghost" href={s.document.url} target="_blank" rel="noreferrer noopener">
            Open the source article
          </a>
        )}
      </div>
    </Chapter>
  );
}
