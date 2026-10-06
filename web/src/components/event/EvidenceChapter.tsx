import { useImpactModel, useMeta } from "../../api/hooks";
import type { EvidenceView, RiskAssessment, RiskSignal, SignalContext, TimelineView } from "../../api/types";
import { ShieldGlyph } from "../icons";
import { StateNotice } from "../StateNotice";
import { Chapter } from "./Chapter";
import { ComparablesPlot } from "./ComparablesPlot";
import { Coverage } from "./Coverage";
import { KnowledgeTimeline } from "./KnowledgeTimeline";
import { useOpenDrawer } from "../Drawer";
import { AnaloguesPanel } from "../assessment/AnaloguesPanel";
import { ExternalMarketCard } from "../markets/ExternalMarketCard";
import { AssessmentTimeline } from "../assessment/AssessmentTimeline";
import { EvidenceGroups } from "../assessment/EvidenceGroups";
import { Skeleton } from "../ui";

/** Chapter 4: what supports the estimate (comparable history, coverage) and what EventShock knew at each moment. */
export function EvidenceChapter({
  s,
  ctx,
  ctxLoading,
  ctxError,
  asOf,
  label,
  a,
  evidence,
  timeline,
  assessLoading,
}: {
  s: RiskSignal;
  ctx: SignalContext | undefined;
  ctxLoading: boolean;
  ctxError: Error | null;
  asOf: string;
  label: (c: string) => string;
  a?: RiskAssessment;
  evidence?: EvidenceView;
  timeline?: TimelineView;
  assessLoading?: boolean;
}) {
  const audit = s.provenance?.impact;
  const modelled = !!audit && s.impact?.comparable_events != null;
  const { data: card } = useImpactModel(modelled);
  const scope = audit ? card?.scopes.find((x) => x.scope === audit.scope) : undefined;
  const [, setOpen] = useOpenDrawer();
  const { data: meta } = useMeta();
  const analoguesOn = !!meta?.capabilities?.analogues;
  return (
    <Chapter
      id="evidence"
      eyebrow="Evidence"
      title="What supports it, and what was known when"
      lede={
        a
          ? "Three kinds of support, kept apart: the source text, the model's inference, and the scenario's assumptions. Then precedent from history, and exactly what EventShock knew, and when."
          : "History that resembles this estimate, who else reported the story, and a timeline you can move through to see exactly what EventShock knew."
      }
    >
      {a && (
        <>
          {evidence ? <EvidenceGroups ev={evidence} /> : assessLoading ? <Skeleton className="h-48 w-full" /> : null}
          <AnaloguesPanel signalId={s.id} enabled={analoguesOn} />
          <ExternalMarketCard eventId={s.id} />
          <div className="mt-10">
            <h3 className="text-lg font-semibold">What did EventShock know at this moment?</h3>
            <p className="mb-5 mt-1 max-w-[70ch] text-sm text-muted">
              The score reads the report and only what existed before it. Later facts are listed so you can audit them, and are marked as never used.
            </p>
            {timeline ? <AssessmentTimeline tl={timeline} /> : assessLoading ? <Skeleton className="h-40 w-full" /> : null}
          </div>
          <details className="disclosure mt-8">
            <summary>Replay it moment by moment, and the reference model's history</summary>
            <div className="mt-5 space-y-8">
              <KnowledgeTimeline s={s} ctx={ctx} loading={ctxLoading} error={ctxError} label={label} />
              <div className="evidence-grid">
                <div>
                  {modelled && s.impact ? (
                    <ComparablesPlot impact={s.impact} baseRate={scope?.calibration?.base_rate_extreme} />
                  ) : (
                    <StateNotice tone="info" what="No comparable events for the reference score" why="Comparable events are statistics of the trained model's own history; none is invented." />
                  )}
                </div>
                <Coverage s={s} asOf={asOf} />
              </div>
            </div>
          </details>
        </>
      )}
      {!a && (
      <>
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
      </>
      )}

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
