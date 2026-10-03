/**
 * Fixed TeX templates for the maths the app shows. Only numbers from structured API fields are interpolated (never API strings),
 * and every template mirrors the code it describes:
 *   impact target + score map  -> configs/modeling.yaml, configs/impact_model.yaml, pipeline/impact_model.py
 *   stress scaling + revaluation -> configs/app.yaml, services/stress_service.py, stress/engine.py
 *   sentiment / event decision -> pipeline/sentiment_model.py, pipeline/event_model.py
 */
const f = (x: number, d = 2) => x.toFixed(d);
const fi = (x: number) => (Number.isInteger(x) ? x.toFixed(0) : x.toFixed(1));

export const TARGET = String.raw`z \;=\; \frac{\mathrm{CAR}_{[s_0,\,s_0+1]}}{\hat\sigma_{\mathrm{idio}}\sqrt{2}}`;
export const TARGET_READING = "The thing the model predicts: how large the company's abnormal return over the two sessions after the report is, in units of its own usual volatility. Direction is not modelled.";

export const PREDICTION = String.raw`\hat y \;=\; \ln\!\bigl(1+\widehat{|z|}\bigr)`;
export const PREDICTION_READING = "The model's raw output is the logarithm of the expected size of the move.";

export const SCORE_CHAIN = String.raw`u=F_{\mathrm{oof}}(\hat y)\;\longrightarrow\; z^{\star}=Q_{\mathrm{real}}(u)\;\longrightarrow\; v=\operatorname{interp}\bigl(z^{\star};\,\text{knots}\bigr)\;\longrightarrow\; I=\min\!\bigl(10,\max(1,\lceil v\rceil)\bigr)`;
export const SCORE_CHAIN_READING =
  "The prediction is ranked against what the model predicted for past events it did not train on (u), mapped to the move events of that rank really produced (z*), then placed on the fixed 1–10 severity ladder.";

export const SCORE_KNOTS: { z: string; v: number }[] = [
  { z: "0", v: 0 },
  { z: "0.5", v: 1 },
  { z: "1", v: 2 },
  { z: "1.5", v: 3 },
  { z: "2", v: 4 },
  { z: "2.5", v: 5 },
  { z: "3", v: 6 },
  { z: "4", v: 7 },
  { z: "5", v: 8 },
  { z: "7", v: 9 },
  { z: "14", v: 10 },
];

export const quantise = (raw: number, score: number) =>
  String.raw`I=\min\!\bigl(10,\max(1,\lceil 10\,r\rceil)\bigr)=\min\!\bigl(10,\max(1,\lceil 10\times ${f(raw, 3)}\rceil)\bigr)=${score}`;

export const INTERVAL = String.raw`\bigl[I_{10},\,I_{90}\bigr]=\text{10th and 90th percentile of the score comparable past events realised}`;

export const stressScale = (impact: number, ref: number, lo: number, hi: number, scale: number) =>
  String.raw`s=\operatorname{clamp}\!\left(\frac{I}{I_{\mathrm{ref}}},\,${f(lo, 1)},\,${f(hi, 1)}\right)=\operatorname{clamp}\!\left(\frac{${fi(impact)}}{${fi(ref)}},\,${f(lo, 1)},\,${f(hi, 1)}\right)=${f(scale, 3)}`;

export const SHOCK_SCALING = String.raw`\text{shock}'=\text{shock}\times s,\qquad m'=1+(m-1)\,s\;\;\text{(PD multipliers)}`;

export const REVALUATION: { id: string; title: string; tex: string; reading: string }[] = [
  { id: "equity", title: "Equities", tex: String.raw`\Delta V = V\,\beta\,s_{\mathrm{eq}}\;\;(\text{market shock}),\qquad \Delta V = V\,s_{\mathrm{eq}}\;\;(\text{sector or issuer shock})`, reading: "Market value times the equity shock, times beta when the shock is market-wide." },
  { id: "bond", title: "Bonds", tex: String.raw`\frac{\Delta P}{P}=-D\,\frac{\Delta r+\Delta\text{spread}}{10^{4}}\quad(\geq -100\%)`, reading: "Duration times the move in rates and spread (in basis points), floored at a total loss." },
  { id: "loan", title: "Loans", tex: String.raw`\mathrm{PD}'=\min\!\bigl(1,\mathrm{PD}\,(1+(m'-1)\,\mathrm{sens})\bigr),\;\; \mathrm{LGD}'=\mathrm{LGD}+a,\;\; \Delta V=-\bigl(\mathrm{EAD}\,\mathrm{PD}'\mathrm{LGD}'-\mathrm{EAD}\,\mathrm{PD}\,\mathrm{LGD}\bigr)`, reading: "Expected loss after the shock minus expected loss before it." },
  { id: "derivative", title: "Derivatives", tex: String.raw`\Delta V=\delta\cdot N_{\mathrm{und}}\cdot s_{\mathrm{eq}}\;\;(\times\beta\text{ for a market shock})`, reading: "Delta times the underlying notional times the equity shock." },
];

export const SENTIMENT = String.raw`\text{score}=P(\text{positive})-P(\text{negative}),\qquad P=\operatorname{softmax}\!\left(\frac{\mathbf{z}}{T}\right)`;
export const SENTIMENT_READING = "A text classifier gives three probabilities (calibrated by a temperature T); the score is positive minus negative, from −1 to +1.";

export const eventDecision = (commit: number) =>
  String.raw`\hat c=\arg\max_k P_k\quad\text{committed only if}\quad P_{\hat c}\ge ${f(commit, 2)}\;\;\text{otherwise: uncertain}`;
export const EVENT_READING = "Nine calibrated probabilities (eight event types plus “not an event”). The model commits to a label only when it is confident enough; otherwise it abstains.";
