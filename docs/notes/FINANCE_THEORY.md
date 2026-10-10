# Finance theory behind EventShock (Stage 8)

What financial quantity should EventShock estimate, which established methods bear on it, which of them the data held here can support, and what was decided. Every claim is tagged:

- **[T]** established theory or published method (cited, and each citation was looked up, not recalled)
- **[E]** empirical evidence produced in this repository (file named; numbers are test-pinned or reproducible)
- **[P]** project methodology (a choice made here)
- **[H]** engineering heuristic
- **[A]** assumption

Pre-registration: `configs/evidence_v3.yaml` (sha256 recorded in every Stage 8 evidence file). Journal: `docs/notes/PROJECT_JOURNEY.md`, Stage 8.

## 1. The question: what should "severity" be?

Candidates considered: expected abnormal return; volatility-adjusted expected move; probability of a material move; expected loss; an ordinal risk category.

**Decision [P].** Severity stays a transparent *ordinal consequence scale* (how serious a kind of development usually is, and how far it reaches), not a price forecast. Three reasons, in order of weight:

1. **The data cannot support a text-to-move forecast.** [E] `docs/evidence/outcome_audit.json`: news episodes about the 34 large caps are barely distinguishable from ordinary days (stratified AUC of |z| 0.523 [0.512, 0.532]; 0.508 [0.500, 0.517] once episodes with an earnings reaction in the window are excluded; P(|z| >= 2) 5.1% vs 4.9% on quiet days). Earnings is the one clear exception (AUC about 0.80 with earnings in the window). A forecast trained on these labels would reproduce the volatility regime and the earnings calendar and call it "event impact" (Stage 4 already found placebo skill >= real skill for `impact-v2`: `docs/notes/EVIDENCE_V2.md`).
2. **The downstream consumer needs a scale, not a point forecast.** The stress engine uses severity to decide whether a scenario triggers and how hard its (assumed) shocks are applied, `scale = clamp(severity / reference, 0.5, 1.5)`. [P]
3. **Honesty about what the score is.** [E] `docs/evidence/severity_validity.json`: the text-only scorecard does not rank realised moves out of sample (2025 test rank correlation +0.007 [-0.025, +0.039]; 2026 live -0.021 [-0.086, +0.040]). The label is therefore `HEURISTIC_UNCALIBRATED`: a transparent triage scale, not an outcome-calibrated one. See §8.

What the realised outcome *is* used for: as hindsight evidence next to retrieved historical analogues (`docs/notes/ANALOGUES.md`), never as a score input.

## 2. Event studies [T]

The abnormal return of a security around an event is its return minus the return a benchmark model predicts without the event (MacKinlay 1997; Campbell, Lo and MacKinlay 1997, ch. 4; Brown and Warner 1985). EventShock's outcome (`modeling/market.py`) is a trailing two-factor market model:

```
AR_k  = r_k - a - b * m_k - c * p_k        m: S&P 500 return, p: equal-weight ex-self sector-peer return
CAR   = sum of AR_k over the reaction window [s0, s0 + W - 1], W = 2 sessions
z     = CAR / (sigma * sqrt(W))            sigma: residual volatility before s0
```

`a, b, c` are fitted by OLS on the 250 sessions strictly before `s0`; nothing at or after `s0` reaches the fit [P] (a test scrambles every price from `s0` on). The market-wide scope uses the S&P 500's excess move with no beta [P].

Choices and what the audit found:

| choice | what it is | audit result [E] (`outcome_audit.json`) |
|---|---|---|
| Daily returns, close to close | no intraday data held | a report's reaction can precede its recorded time for crawl-timestamped sources |
| Clock assignment | after-close and weekend reports react the next session (`pipeline.market_context.anchor_session`); crawl times are flagged FIRST_SEEN | placebo/real mean log-severity is about 1.0 for FIRST_SEEN, IN_SESSION and OFF_HOURS: those clocks carry no more signal after the report than before it |
| Window W = 2 | reaction on the report session or the next | unchanged |
| Sigma | **outcome-v2**: 60-session residual RMS. **outcome-v3**: RiskMetrics EWMA, lambda 0.94, seeded with the 60-session RMS | pre-registered rule met: EWMA removes 88% of the regime variance gap (|ln Var(z\|high VIX)/Var(z\|low VIX)| 0.090 -> 0.010), in both halves of the sample; adopted as outcome-v3 **for the side-car layers only** |
| Estimation windows are not cleaned of other events | MacKinlay recommends excluding them | 87% of 60-session windows hold an earnings reaction; sigma is inflated about 15% on average. Diagnostic only; no remedy applied this round |
| Independence of event dates | event-date clustering inflates t-statistics (Kolari and Pynnonen 2010; BMP 1991 for event-induced variance) | intraclass correlation 0.067, design effect 2.18, effective n 8,995 of 19,638. **Every Stage 8 interval is a cluster bootstrap over reaction dates** [P] |

Normalisation quality [E]: on quiet days with no earnings in the window, sigma60 gives Var(z) = 0.98 and P(|z| > 2) = 4.9% (Gaussian 4.55%): the target construction is sound where it should be. Including earnings sessions the tails are fat (excess kurtosis 11.8, P(|z|>2) 6.0%), which is the earnings effect, not a normalisation failure. Both are in the evidence file; the first run's "quiet" null still contained earnings sessions, which was corrected by a post-hoc, disclosed block (the pre-registered decision does not use it).

Not used and why: buy-and-hold abnormal returns (a long-horizon quantity; our windows are two sessions, where BHAR and CAR coincide to first order); cross-sectional significance tests such as BMP or Kolari-Pynnonen as *tests* (we do not test a hypothesis about an event class; we use the clustered bootstrap for intervals) [P].

## 3. Volatility and regime [T] / [E]

- **Realised volatility** is the baseline normaliser (sigma60).
- **EWMA** (RiskMetrics 1996, lambda 0.94 for daily data) is the one alternative tested, because it reacts to regime change faster than a fixed window. It is a one-parameter special case of the ARCH family (Engle 1982) without estimation risk [T]. **Adopted for outcome-v3** by the pre-registered rule [E].
- **GARCH-type models**: rejected [P]. A 60-session RMS and an EWMA already normalise the null to within a few percent once earnings are separated; a fitted GARCH over 34 names adds estimation risk and a dependency without a measurable gain to test against.
- **VIX** (Whaley 2000) is the market's own forward volatility measure. It enters the severity scorecard as one bounded adjustment under an explicit freshness policy (last completed session, at most one session behind, else excluded with the reason) [P], and is the regime control in every validity test. Implied volatility of single names is not held [A].

## 4. Systemic risk and contagion

Co-movement and connectedness measures (Billio, Getmansky, Lo and Pelizzon 2012) require long return histories of a broad set of institutions and their cross-holdings. Rejected [P]: the universe is 34 current large caps with no balance-sheet linkage data, so a network estimate would be unidentified and its precision invented. Systemic scale enters the scorecard only as an anchored judgement (the *reach* answer: firm / sector / market / global) [P], and is labelled as such.

## 5. Portfolio risk and stress testing

- **Stress testing** is scenario analysis whose magnitudes are assumptions; supervisory guidance asks that scenarios be severe but plausible and that their limitations be stated (BCBS 155, 2009, now superseded) [T]. EventShock's scenarios are labelled illustrative and are not calibrated to a regulatory framework [P].
- **Coherent measures** (Artzner, Delbaen, Eber and Heath 1999) and **Expected Shortfall** (Acerbi and Tasche 2002) are the reference risk measures. **VaR/ES by historical simulation is rejected** for this book [P]: the portfolio is synthetic and its positions are not mapped to price histories, so a historical-simulation tail would be fabricated precision.
- **Deterministic revaluation** [P]: equity `dV = V * beta * s` (market scope) or `V * s`; bonds `dP/P = -D * dy + 0.5 * C * dy^2` with `dy = (d_rates + d_spread)/10^4` (the convexity term only for a position that carries `convexity`; otherwise first order); loans `EL = EAD * PD' * LGD'`, and for a loan that carries `spread_passthrough` a spread shock also raises the hazard rate (credit triangle, spread = hazard x LGD: `h' = h + passthrough * ds / LGD`, `PD' = 1 - exp(-h' T)`); derivatives `dV = delta * notional * s + 0.5 * gamma * notional * s^2` (gamma only when set) and, for one that names a counterparty, a CVA term `d(PD x LGD x max(MTM, 0))`. Same inputs, same result; no randomness.
- **Stage 13 mechanics are opt-in and illustrative** [P]: each lives on a position field that is omitted when unset, so the default book's hash and every pinned run are unchanged. They are textbook approximations, not a calibrated model: the credit triangle ignores recovery-timing and risk premia, the CVA uses the positive mark-to-market as the whole expected exposure (no netting, collateral or exposure profile), and gamma is a second-order term in the underlying's return. Wholesale Book v2 fills them with fixed-seed synthetic values (`portfolio/book_v2.py`); ratings there are internal PD buckets, not agency ratings.
- **New in Stage 8: a historical reality check of each shock, arithmetic untouched** (`stress/history_check.py`, `data/replay/market/shock_history.json`, `GET /api/scenarios/{id}/history-check`). Equity (S&P 500, sector baskets, single names) and 10-year-yield shocks are ranked against the empirical 1-, 5- and 21-session move distributions since 2014; credit-spread, PD and LGD shocks are reported as **not checkable** (no free history is held). [E] Examples: a -8% S&P 500 move over one session occurred in about 1 of 1,600 windows; the +100 bp parallel rate shock in `scn_macro_rates_shock` is larger than the worst 21-session change on record (+93 bp). A percentile is a historical frequency, not a probability; overlapping windows are autocorrelated, so independent windows are about n/k [T].
- **Rate transmission** (Bernanke and Kuttner 2005): unanticipated policy moves have a measurable equity response; EventShock does not model the transmission, it applies configured parallel shifts [P].

## 6. Risk scoring, calibration, uncertainty

- **Proper scoring and calibration** (Gneiting and Raftery 2007; Niculescu-Mizil and Caruana 2005; Guo et al. 2017) are used for the trained probability models (event, impact) [T]. The 1-10 severity is not a probability and is not presented as one [P].
- **Ordinal or ML severity on text: rejected** [P]. It needs outcome labels that measure text-driven severity; the realised move is dominated by regime and the earnings calendar (§1), so a fitted model would learn those.
- **Calibration table** [E]: the pre-registered band-versus-outcome table is published with Wilson intervals. It is not monotone (dev tail rate by band: negligible 12.6%, low 11.3%, moderate 14.8%, high 11.2%, extreme 13.3%; abstained 6.8%), so the scale is labelled heuristic.
- **Uncertainty** [P]: the severity score carries an assumption-sensitivity range (anchors, factors and adjustments perturbed), explicitly not a statistical interval; every evidence interval is a clustered bootstrap.

## 7. Text, embeddings and retrieval

- Financial text and returns (Tetlock 2007; Loughran and McDonald 2011): tone has a weak, short-lived relation with returns in aggregate and in curated corpora [T]. Here sentiment matches the realised sign about 53% of the time [E] (`docs/notes/IMPACT_MODEL.md`), so tone is not a severity input [P].
- **Embeddings** (Reimers and Gurevych 2019; E5, Wang et al. 2022) help *finding similar text*, not predicting returns [E]: they improved event-type classification when fused with TF-IDF (`docs/notes/EVIDENCE_V2.md`), never lowered held-out impact error (`docs/notes/IMPACT_MODEL.md` section 11), and in Stage 8 they beat TF-IDF at retrieving same-event-type reports on unseen wording (P@5 0.504 vs 0.443; non-NONE queries 0.389 vs 0.255; `docs/evidence/analogue_relevance.json`).
- **Retrieval of historical analogues** is therefore an *explanation and context* layer, with the outcome shown as hindsight and an explicit "no reliable analogue" state. Method and results: `docs/notes/ANALOGUES.md`.

## 8. Evaluation integrity

- Chronological splits with an embargo (López de Prado 2018): train through 2023, validation 2024, test 2025, live 2026; a five-session embargo; analogue eligibility additionally requires the analogue's whole reaction window plus the embargo to have closed before the query [P] (test: future invariance).
- Multiple testing and data snooping (White 2000; Hansen 2005): every decision rule is written before any result (`configs/evidence_v3.yaml`); no cue, anchor or threshold is edited after a result; post-hoc analyses are labelled as such and never change a label [P].
- The held-out benchmark sets of Stage 7 are untouched.

## 9. Method assessment (the ten questions, condensed)

| method | measures | data needed / held | key assumption | leakage risk | out-of-sample testable | verdict |
|---|---|---|---|---|---|---|
| Two-factor market-model CAR | abnormal move | prices (held, local) | stable betas over 250 sessions | none if the fit is trailing | yes | **kept** (outcome-v2/v3) |
| Volatility-normalised z | move in own-sigma units | prices | residuals roughly iid | none | yes | **kept** |
| EWMA sigma | regime-aware sigma | prices | lambda 0.94 | none | yes (audit) | **adopted for side-cars** |
| GARCH | conditional variance | prices | model form | none | yes | rejected (no testable gain) |
| BHAR / long windows | long-horizon drift | prices | n/a | high (overlap) | weak | rejected |
| BMP / Kolari-Pynnonen tests | event-mean significance | cross-section of events | clustering | none | n/a | not needed; cluster bootstrap used |
| VIX regime | market-implied vol | VIX (held) | none | stale data | yes | **kept**, freshness policy |
| Network/contagion | spillovers | cross-holdings (not held) | linkage observable | n/a | no | rejected |
| Portfolio VaR/ES by history | tail loss | position price histories (not held) | stationarity | n/a | no | rejected |
| Duration/convexity | rate sensitivity | bond terms (synthetic) | small shocks | none | n/a | duration kept; **convexity added opt-in in Stage 13** for the synthetic Book v2 only |
| Ordinal/ML severity on text | learned severity | outcome labels for text | labels valid | high | yes | rejected (labels invalid) |
| Embedding retrieval | similar precedent | text + outcomes (held) | similarity ~ relevance | high (duplicates, overlap) | yes | **kept as evidence layer** |
| Reference-class forecast | cell mean of outcomes | outcomes (held) | exchangeability within cell | low | yes | tested (`analogue_outcome_value.json`) |

## 10. Limitations

34 current large caps (survivorship); headline-only text; a 6% GDELT sample for 2023-2025 and almost no news for 2021-2022; thin tails (about 2.7% of issuer episodes at severity >= 7); weak clocks for most news (FIRST_SEEN); the outcome is coincident with coverage, so it is a response proxy, not a clean forecast; scenario shocks are assumptions, now at least ranked against history; credit and default magnitudes cannot be checked; one regime (2014-2026).

## References (verified)

- MacKinlay, A. C. (1997). Event studies in economics and finance. *Journal of Economic Literature* 35(1), 13-39.
- Brown, S. J. and Warner, J. B. (1985). Using daily stock returns: the case of event studies. *Journal of Financial Economics* 14, 3-31.
- Boehmer, E., Musumeci, J. and Poulsen, A. B. (1991). Event-study methodology under conditions of event-induced variance. *Journal of Financial Economics* 30, 253-272.
- Kolari, J. W. and Pynnonen, S. (2010). Event study testing with cross-sectional correlation of abnormal returns. *Review of Financial Studies* 23(11), 3996-4025.
- Campbell, J. Y., Lo, A. W. and MacKinlay, A. C. (1997). *The Econometrics of Financial Markets*. Princeton University Press.
- J.P. Morgan / Reuters (1996). *RiskMetrics Technical Document*.
- Engle, R. F. (1982). Autoregressive conditional heteroscedasticity with estimates of the variance of United Kingdom inflation. *Econometrica* 50(4), 987-1007.
- Whaley, R. E. (2000). The investor fear gauge. *Journal of Portfolio Management* 26(3), 12-17.
- Billio, M., Getmansky, M., Lo, A. W. and Pelizzon, L. (2012). Econometric measures of connectedness and systemic risk in the finance and insurance sectors. *Journal of Financial Economics*.
- Artzner, P., Delbaen, F., Eber, J.-M. and Heath, D. (1999). Coherent measures of risk. *Mathematical Finance* 9(3), 203-228.
- Acerbi, C. and Tasche, D. (2002). On the coherence of expected shortfall. *Journal of Banking and Finance* 26(7), 1487-1503.
- Basel Committee on Banking Supervision (2009). *Principles for sound stress testing practices and supervision* (BCBS 155; superseded).
- Bernanke, B. S. and Kuttner, K. N. (2005). What explains the stock market's reaction to Federal Reserve policy? *Journal of Finance* 60(3), 1221-1257.
- Tetlock, P. C. (2007). Giving content to investor sentiment: the role of media in the stock market. *Journal of Finance* 62, 1139-1168.
- Loughran, T. and McDonald, B. (2011). When is a liability not a liability? Textual analysis, dictionaries, and 10-Ks. *Journal of Finance* 66(1), 35-65.
- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association* 102(477), 359-378.
- Niculescu-Mizil, A. and Caruana, R. (2005). Predicting good probabilities with supervised learning. *ICML*.
- Guo, C., Pleiss, G., Sun, Y. and Weinberger, K. Q. (2017). On calibration of modern neural networks. *ICML* (PMLR 70).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- White, H. (2000). A reality check for data snooping. *Econometrica* 68(5), 1097-1126.
- Hansen, P. R. (2005). A test for superior predictive ability. *Journal of Business and Economic Statistics* 23, 365-380.
- Reimers, N. and Gurevych, I. (2019). Sentence-BERT: sentence embeddings using siamese BERT-networks. *EMNLP-IJCNLP*.
- Wang, L. et al. (2022). Text embeddings by weakly-supervised contrastive pre-training (E5). arXiv:2212.03533.
