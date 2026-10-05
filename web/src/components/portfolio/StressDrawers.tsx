import type { Scenario, StressResult } from "../../api/types";
import * as TeX from "../../lib/formulas";
import { Drawer, DrawerSection, useOpenDrawer } from "../Drawer";
import { Formula } from "../Math";
import { HistoryCheck } from "./HistoryCheck";
import { AuditPanel, PositionsTable, ShocksTable } from "../stress";

/** The stress page's drawers (?open=math|assumptions|positions|audit): the arithmetic, the assumptions, every position, the audit trail. */
export function StressDrawers({ r, scenario }: { r: StressResult | undefined; scenario?: Scenario }) {
  const [open, setOpen] = useOpenDrawer();
  const close = () => setOpen(null);
  const sev = r?.severity;
  return (
    <>
      <Drawer open={open === "math" && !!sev} onClose={close} title="How the scenario is calculated" eyebrow="Mathematics" wide>
        {sev && (
          <>
            <p className="mb-4 max-w-[62ch] text-ink-2">
              The scenario's shocks are chosen assumptions. The event's impact only decides how hard they are applied; the engine then revalues every position with fixed formulas. No randomness, no model.
            </p>
            <DrawerSection title="1 · How hard the scenario is applied">
              <Formula
                tex={TeX.stressScale(sev.impact_used, sev.reference_impact, sev.min_scale, sev.max_scale, sev.scale)}
                reading={`Impact ${sev.impact_used} against a reference of ${sev.reference_impact} gives a scale of ${sev.scale.toFixed(3)}, kept between ${sev.min_scale} and ${sev.max_scale}.`}
              />
              <div className="mt-4">
                <Formula tex={TeX.SHOCK_SCALING} reading="Every shock is multiplied by the scale; a default-probability multiplier scales its excess over 1." />
              </div>
            </DrawerSection>
            <DrawerSection title="2 · How each kind of position is revalued" note="The most specific scope wins per factor (issuer, then sector, then market-wide), so nothing is counted twice.">
              <div className="space-y-5">
                {TeX.REVALUATION.map((v) => (
                  <div key={v.id}>
                    <h4 className="mb-1 text-sm font-medium">{v.title}</h4>
                    <Formula tex={v.tex} reading={v.reading} />
                  </div>
                ))}
              </div>
            </DrawerSection>
          </>
        )}
      </Drawer>
      <Drawer open={open === "assumptions" && !!r} onClose={close} title="Scenario assumptions" eyebrow={scenario?.name ?? "Scenario"} wide>
        {r && (
          <>
            <p className="mb-4 max-w-[62ch] text-sm text-muted">Illustrative magnitudes chosen for the scenario template, not forecasts. Shown at the template's reference impact and as applied here.</p>
            <ShocksTable shocks={r.shocks} scenario={scenario} bare />
            <HistoryCheck scenarioId={scenario?.id} scale={r.severity?.scale ?? 1} />
          </>
        )}
      </Drawer>
      <Drawer open={open === "positions" && !!r} onClose={close} title="Every position" eyebrow="Audit" wide>
        {r && <PositionsTable positions={r.positions} bare />}
      </Drawer>
      <Drawer open={open === "audit" && !!r} onClose={close} title="Audit trail" eyebrow="Same inputs, same result">
        {r && <AuditPanel r={r} bare />}
      </Drawer>
    </>
  );
}
