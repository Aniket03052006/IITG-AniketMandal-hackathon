"""Gold set: a stratified, blind sample built to find where the automatic labels are wrong, plus validate/score tooling.

Design (docs/GOLD_LABELING_GUIDE.md):
* Two populations. ``tfn``: news tweets from the Twitter-Financial-News topic corpus, ~6 per topic, to measure the
  precision of the 20-topic -> 8-class crosswalk. ``history``: documents from our own sources (the deployment
  distribution).
* History strata, assigned by first match: hard entity/timing cases -> rare placeholder classes -> placeholder/probe
  disagreements -> a uniform residual sample per source. Every stratum is a seeded simple random sample, so each row has
  inclusion probability n_k/N_k and weight N_k/n_k; weighted estimates cover the whole (template-collapsed) population.
  ``rand:*`` and ``tfn:*`` are exact SRS strata. The others ("targeted") are SRS capped per issuer, so their weights
  are approximate, and their few rows carry large weights: use them to discover errors per class (unweighted) rather
  than to estimate prevalence.
* The sheet is blind: it carries no placeholder class, probe output, topic or stratum. Those live in the manifest,
  which a labeler must not open until the labels are final.
* Texts that are near-duplicates of TFN training text are dropped from the history pool, and near-duplicate templates
  (spam, boilerplate) are collapsed to one representative before the population is counted.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain import EventCategory
from ..ingestion.snapshot import atomic_write_text
from ..pipeline.config import EnrichmentConfig
from ..pipeline.enrich import EnrichmentInput, PlaceholderEnricher
from ..pipeline.normalize import content_tokens
from .config import GoldConfig
from .corpora import HistoryDoc, TextPool
from .text import has_near_duplicate, template_key

EVENT_CLASSES = [c.value for c in EventCategory]
EVENT_VOCAB = [*EVENT_CLASSES, "NONE"]  # NONE = not an event (chatter, promotion, opinion, no news)
SENTIMENT_VOCAB = ["-1", "0", "1"]
ENTITY_VOCAB = ["y", "n", "na"]
SHEET_COLUMNS = ["gold_id", "source", "published_at", "ticker", "text",
                 "ai_sentiment", "ai_event_class", "ai_secondary_class", "ai_entity_ok", "ai_notes"]
ADJ_COLUMNS = ["gold_id", "text", "ai_sentiment", "ai_event_class", "ai_secondary_class", "ai_entity_ok", "ai_notes",
               "human_sentiment", "human_event_class", "human_entity_ok", "human_notes"]
ANNOTATOR = "ai:claude"
SENTIMENT_NAME = {"negative": "-1", "neutral": "0", "positive": "1"}


def _h(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


# ----------------------------------------------------------------------------------------- weak probe (stdlib)
class NaiveBayes:
    """Presence-based multinomial naive Bayes on content tokens. Deterministic; used only to *find* disagreements."""

    def __init__(self, alpha: float = 0.5) -> None:
        self.alpha = alpha
        self.classes: list[str] = []
        self.prior: dict[str, float] = {}
        self.counts: dict[str, Counter[str]] = {}
        self.totals: dict[str, int] = {}
        self.vocab: set[str] = set()

    def fit(self, texts: Sequence[str], labels: Sequence[str]) -> NaiveBayes:
        self.classes = sorted(set(labels))
        self.counts = {c: Counter() for c in self.classes}
        n = Counter(labels)
        for t, lab in zip(texts, labels, strict=True):
            toks = content_tokens(t)
            self.counts[lab].update(toks)
            self.vocab |= toks
        self.totals = {c: sum(self.counts[c].values()) for c in self.classes}
        self.prior = {c: math.log(n[c] / len(labels)) for c in self.classes}
        return self

    def proba(self, text: str) -> dict[str, float]:
        toks = [t for t in content_tokens(text) if t in self.vocab]
        v = len(self.vocab)
        logp = {c: self.prior[c] + sum(math.log((self.counts[c][t] + self.alpha) / (self.totals[c] + self.alpha * v)) for t in toks)
                for c in self.classes}
        m = max(logp.values())
        z = sum(math.exp(x - m) for x in logp.values())
        return {c: math.exp(x - m) / z for c, x in logp.items()}

    def predict(self, text: str) -> tuple[str, float]:
        p = self.proba(text)
        best = max(sorted(p), key=p.__getitem__)
        return best, p[best]


# ---------------------------------------------------------------------------------------------- sampling
@dataclass
class Candidate:
    key: str  # origin id
    population: str  # "tfn" | "history"
    stratum: str
    text: str
    source: str
    published_at: str
    ticker: str
    issuer: str
    weak: dict[str, Any]


def _sentiment_sign(x: float, eps: float = 0.12) -> str:
    return "1" if x > eps else "-1" if x < -eps else "0"


def sentiment_label_from_probs(p: dict[str, float]) -> str:
    return SENTIMENT_NAME[max(sorted(p), key=p.__getitem__)]


def _select(cands: list[Candidate], n: int, seed: int, issuer_cap: int | None) -> list[Candidate]:
    """First ``n`` by seeded hash. With ``issuer_cap`` an issuer holds at most that many slots while others remain;
    if the quota still cannot be met, the cap is relaxed (a short stratum is worse than a lopsided one)."""
    ordered = sorted(cands, key=lambda c: _h(seed, c.key))
    out, per_issuer = [], Counter()
    for c in ordered:
        if len(out) >= n:
            break
        if issuer_cap is not None and c.issuer and per_issuer[c.issuer] >= issuer_cap:
            continue
        per_issuer[c.issuer] += 1
        out.append(c)
    if len(out) < n:
        taken = {c.key for c in out}
        out += [c for c in ordered if c.key not in taken][: n - len(out)]
    return out


def build_sample(cfg: GoldConfig, *, history: Iterable[HistoryDoc], topic_pool: TextPool, sentiment_pool: TextPool,
                 enrichment_cfg: EnrichmentConfig) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Returns (sheet rows, manifest). Deterministic for a given seed, config and inputs."""
    enricher = PlaceholderEnricher(enrichment_cfg)

    def placeholder(text: str) -> tuple[str, float]:
        e = enricher.enrich(EnrichmentInput(text=text, source_label=None, unique_domains=1))
        return e.event.category.value, e.sentiment.score

    # weak probes: naive Bayes trained on the trainable tiers (strong+medium) and on the human sentiment labels
    train_topic = [e for e in topic_pool.examples if e.label != "UNMAPPED" and e.tier in ("strong", "medium")]
    nb_event = NaiveBayes().fit([e.text for e in train_topic], [e.label for e in train_topic])
    nb_sent = NaiveBayes().fit([e.text for e in sentiment_pool.examples], [SENTIMENT_NAME[e.label] for e in sentiment_pool.examples])

    cands: list[Candidate] = []
    # ---- TFN topic population: one representative per near-duplicate group, labelled topics only (all 20 incl. unmapped)
    seen_groups: set[int] = set()
    for e, g in sorted(zip(topic_pool.examples, topic_pool.groups, strict=True), key=lambda x: _h(cfg.seed, x[0].id)):
        if g in seen_groups:
            continue
        seen_groups.add(g)
        pev, psent = placeholder(e.text)
        ne, nep = nb_event.predict(e.text)
        ns, nsp = nb_sent.predict(e.text)
        cands.append(Candidate(e.id, "tfn", f"tfn:{e.topic}", e.text, "tfn-topic (news tweet)", "", "", "", {
            "topic": e.topic, "topic_name": e.topic_name, "tier": e.tier, "mapped_class": None if e.label == "UNMAPPED" else e.label,
            "placeholder_event": pev, "placeholder_sentiment": round(psent, 4), "nb_event": ne, "nb_event_p": round(nep, 3),
            "nb_sentiment": ns, "nb_sentiment_p": round(nsp, 3)}))

    # ---- history pool: drop near-duplicates of TFN text, collapse templates, then partition into strata
    docs = list(history)
    tfn_texts = [e.text for e in topic_pool.examples] + [e.text for e in sentiment_pool.examples]
    dup = has_near_duplicate([d.text for d in docs], tfn_texts, cfg.near_duplicate_threshold)
    docs = [d for d, f in zip(docs, dup, strict=True) if not f]
    rep: dict[str, HistoryDoc] = {}
    for d in docs:
        tk = template_key(d.text)
        key = tk if len(tk.split()) >= 4 else f"id:{d.id}"
        if key not in rep or _h(cfg.seed, d.id) < _h(cfg.seed, rep[key].id):
            rep[key] = d
    docs = sorted(rep.values(), key=lambda d: d.id)
    for d in docs:
        ne, nep = nb_event.predict(d.text)
        ns, nsp = nb_sent.predict(d.text)
        weak = {"placeholder_event": d.placeholder_event, "placeholder_sentiment": round(d.placeholder_sentiment, 4), "nb_event": ne,
                "nb_event_p": round(nep, 3), "nb_sentiment": ns, "nb_sentiment_p": round(nsp, 3), "er_rule": d.er_rule,
                "multi_entity": d.multi_entity, "origin": d.origin, "gkg_tone": d.gkg_tone, "adapter": d.adapter}
        if d.multi_entity:
            stratum = "hard:multi_entity"
        elif d.er_rule in ("WEAK_ALIAS", "FUZZY", "BARE_TICKER"):
            stratum = "hard:weak_entity_rule"
        elif d.origin == "SOURCE_DATE_ONLY":
            stratum = "hard:date_only"
        elif d.placeholder_event in {c.value for c in cfg.rare_class_per_class}:
            stratum = f"rare:{d.placeholder_event}"
        elif d.placeholder_event == "MARKET_VALUATION" and nep >= 0.6 and ne != "MARKET_VALUATION":
            stratum = "dis:event"
        elif nsp >= 0.55 and _sentiment_sign(d.placeholder_sentiment) not in ("0", ns):
            stratum = "dis:sentiment"
        else:
            stratum = f"rand:{d.adapter}"
        cands.append(Candidate(d.id, "history", stratum, d.text, d.adapter, d.published_at.isoformat(), d.ticker or "", d.ticker or d.entity_id, weak))

    quotas: dict[str, int] = {"hard:multi_entity": cfg.hard_multi_entity, "hard:weak_entity_rule": cfg.hard_weak_entity_rule,
                              "hard:date_only": cfg.hard_date_only, "dis:event": cfg.disagreement_event,
                              "dis:sentiment": cfg.disagreement_sentiment}
    quotas |= {f"rare:{c.value}": n for c, n in cfg.rare_class_per_class.items()}
    for c in cands:
        if c.stratum.startswith("tfn:"):
            quotas[c.stratum] = cfg.tfn_topic_per_topic
        elif c.stratum.startswith("rand:"):
            quotas[c.stratum] = cfg.random_per_source
    by_stratum: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:
        by_stratum[c.stratum].append(c)

    chosen: list[tuple[Candidate, float, int]] = []  # candidate, rank position in [0,1), n_k
    strata_info: dict[str, dict[str, Any]] = {}
    for name in sorted(by_stratum):
        pool = by_stratum[name]
        n = min(quotas.get(name, 0), len(pool))
        targeted = not (name.startswith("rand:") or name.startswith("tfn:"))
        cap = max(1, math.ceil(cfg.max_issuer_share * n)) if targeted and n else None
        picked = _select(pool, n, cfg.seed, cap)
        strata_info[name] = {"role": "targeted" if targeted else "population", "population_size": len(pool),
                             "sampled": len(picked), "quota": quotas.get(name, 0)}
        for i, c in enumerate(picked):
            chosen.append((c, (i + 0.5) / max(1, len(picked)), len(picked)))
    chosen.sort(key=lambda x: (x[1], _h(cfg.seed, x[0].key)))  # any prefix is a proportionally stratified sample

    rows, items = [], {}
    for i, (c, _, _) in enumerate(chosen, start=1):
        gid = f"G{i:03d}"
        rows.append({"gold_id": gid, "source": c.source, "published_at": c.published_at, "ticker": c.ticker, "text": c.text,
                     **{k: "" for k in SHEET_COLUMNS[5:]}})
        info = strata_info[c.stratum]
        items[gid] = {"origin_id": c.key, "population": c.population, "stratum": c.stratum, "role": info["role"],
                      "weight": round(info["population_size"] / info["sampled"], 6),
                      "weak": c.weak}
    manifest = {"schema": 1, "annotator": ANNOTATOR, "seed": cfg.seed, "rows": len(rows),
                "note": "Labelers must not open this file until the labels are final: it holds the weak labels the sheet hides.",
                "strata": strata_info, "items": items}
    return rows, manifest


# --------------------------------------------------------------------------------------------- sheet I/O
def write_sheet(path: Path, rows: list[dict[str, str]], columns: Sequence[str] = SHEET_COLUMNS) -> None:
    import io

    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(rows)
    atomic_write_text(path, buf.getvalue())


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@dataclass(frozen=True)
class ValidationReport:
    rows: int
    complete: int
    errors: list[str]
    event_distribution: dict[str, int]
    sentiment_distribution: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_sheet(rows: Sequence[dict[str, str]], manifest: dict[str, Any], *, require_complete: bool = False,
                   prefix: str = "ai_", subset: bool = False) -> ValidationReport:
    """``subset=True`` for sheets that deliberately hold only some manifest ids (the consistency sheet)."""
    errors: list[str] = []
    ids = [r.get("gold_id", "") for r in rows]
    if len(set(ids)) != len(ids):
        errors.append("duplicate gold_id values")
    missing = set(manifest["items"]) - set(ids)
    extra = set(ids) - set(manifest["items"])
    if missing and not subset:
        errors.append(f"{len(missing)} manifest ids missing from the sheet, e.g. {sorted(missing)[:3]}")
    if extra:
        errors.append(f"{len(extra)} sheet ids unknown to the manifest, e.g. {sorted(extra)[:3]}")
    complete = 0
    ev, se = Counter(), Counter()
    for r in rows:
        gid = r.get("gold_id", "?")
        s, e, sec, ent = (r.get(prefix + k, "").strip() for k in ("sentiment", "event_class", "secondary_class", "entity_ok"))
        if not (s or e or ent):
            continue
        bad = False
        if s not in SENTIMENT_VOCAB:
            errors.append(f"{gid}: {prefix}sentiment {s!r} not in {SENTIMENT_VOCAB}")
            bad = True
        if e not in EVENT_VOCAB:
            errors.append(f"{gid}: {prefix}event_class {e!r} not in the 8 classes or NONE")
            bad = True
        if sec and (sec not in EVENT_CLASSES or sec == e):
            errors.append(f"{gid}: {prefix}secondary_class {sec!r} must be one of the 8 classes and differ from the primary")
            bad = True
        allowed = {"y", "n"} if r.get("ticker", "").strip() else {"na"}  # no ticker (TFN rows, unresolved history rows) -> na
        if ent not in allowed:
            errors.append(f"{gid}: {prefix}entity_ok {ent!r} must be {' or '.join(sorted(allowed))}")
            bad = True
        if not bad:
            complete += 1
            ev[e] += 1
            se[s] += 1
    if require_complete and complete < len(rows):
        errors.append(f"{len(rows) - complete} of {len(rows)} rows are not completely labelled")
    return ValidationReport(len(rows), complete, errors, dict(sorted(ev.items())), dict(sorted(se.items())))


# ----------------------------------------------------------------------------------------------- scoring
def effective_labels(sheet: Sequence[dict[str, str]], adjudication: Sequence[dict[str, str]] = ()) -> dict[str, dict[str, str]]:
    """Per gold_id: sentiment, event, secondary, entity_ok, source ("ai" | "human"). A non-empty human_* field wins."""
    human = {r["gold_id"]: r for r in adjudication}
    out = {}
    for r in sheet:
        if not r.get("ai_event_class", "").strip():
            continue
        h = human.get(r["gold_id"], {})
        out[r["gold_id"]] = {
            "sentiment": h.get("human_sentiment", "").strip() or r["ai_sentiment"].strip(),
            "event": h.get("human_event_class", "").strip() or r["ai_event_class"].strip(),
            "secondary": r.get("ai_secondary_class", "").strip(),
            "entity_ok": h.get("human_entity_ok", "").strip() or r["ai_entity_ok"].strip(),
            "overridden": "yes" if any(h.get(k, "").strip() for k in ("human_sentiment", "human_event_class", "human_entity_ok")) else "no"}
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 3), round(c + h, 3))


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def weighted_scores(pairs: Sequence[tuple[str, str, float]], classes: Sequence[str]) -> dict[str, Any]:
    """(truth, prediction, weight) -> accuracy, macro-F1 over classes present in truth or prediction, per-class P/R/F1."""
    tot = sum(w for _, _, w in pairs)
    if not tot:
        return {"n": 0}
    acc = sum(w for t, p, w in pairs if t == p) / tot
    per = {}
    for c in classes:
        tp = sum(w for t, p, w in pairs if t == c and p == c)
        fp = sum(w for t, p, w in pairs if t != c and p == c)
        fn = sum(w for t, p, w in pairs if t == c and p != c)
        if tp + fp + fn == 0:
            continue
        pr, rc = tp / (tp + fp) if tp + fp else 0.0, tp / (tp + fn) if tp + fn else 0.0
        per[c] = {"precision": round(pr, 3), "recall": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0,
                  "support": round(sum(w for t, _, w in pairs if t == c), 2)}
    return {"n": len(pairs), "accuracy": round(acc, 4), "macro_f1": round(sum(v["f1"] for v in per.values()) / max(1, len(per)), 4),
            "per_class": per}


def score_gold(sheet: Sequence[dict[str, str]], manifest: dict[str, Any], adjudication: Sequence[dict[str, str]] = (),
               consistency: Sequence[dict[str, str]] = (), tiers: dict[int, str | None] | None = None) -> dict[str, Any]:
    """``tiers`` (topic id -> current tier) overrides the tiers frozen in the manifest at sampling time."""
    lab = effective_labels(sheet, adjudication)
    items = manifest["items"]
    out: dict[str, Any] = {"annotator": manifest.get("annotator"), "labelled": len(lab), "overridden_by_human": sum(v["overridden"] == "yes" for v in lab.values())}

    # ---- the topic -> class crosswalk, per topic
    topics: dict[str, dict[str, Any]] = {}
    for gid, v in lab.items():
        w = items[gid]["weak"]
        if items[gid]["population"] != "tfn":
            continue
        tier = tiers.get(w["topic"], w["tier"]) if tiers else w["tier"]
        t = topics.setdefault(f"{w['topic']:02d} {w['topic_name']}", {"tier": tier, "mapped_class": w["mapped_class"], "n": 0,
                                                                      "match": 0, "none": 0, "gold": Counter()})
        t["n"] += 1
        t["gold"][v["event"]] += 1
        t["match"] += v["event"] == w["mapped_class"] or v["secondary"] == w["mapped_class"] != ""
        t["none"] += v["event"] == "NONE"
    out["topic_mapping_precision"] = {k: {"tier": t["tier"], "mapped_class": t["mapped_class"], "n": t["n"],
                                          "precision_primary_or_secondary": round(t["match"] / t["n"], 3) if t["mapped_class"] else None,
                                          "share_none": round(t["none"] / t["n"], 3), "gold_distribution": dict(t["gold"].most_common(4))}
                                      for k, t in sorted(topics.items())}
    by_tier: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for t in topics.values():
        if t["mapped_class"]:
            by_tier[t["tier"]][0] += t["match"]
            by_tier[t["tier"]][1] += t["n"]
    out["mapping_precision_by_tier"] = {k: round(m / n, 3) for k, (m, n) in sorted(by_tier.items())}

    # ---- the placeholder-v0 enrichment against gold, per population / targeted
    def weak_pairs(kind: str, pred_key: str, pop: str | None, role: str) -> list[tuple[str, str, float]]:
        """role "population": every stratum of ``pop``, inclusion-weighted. role "targeted": targeted strata, unweighted."""
        res = []
        for gid, v in lab.items():
            it = items[gid]
            if (role == "targeted" and it["role"] != "targeted") or (pop and it["population"] != pop):
                continue
            w = it["weak"]
            pred = w[pred_key] if (kind == "event" or pred_key == "nb_sentiment") else _sentiment_sign(float(w[pred_key]))
            res.append((v[kind], pred, it["weight"] if role == "population" else 1.0))
        return res

    result: dict[str, Any] = {}
    for role, pops in (("population", ("history", "tfn")), ("targeted", ("history",))):
        for pop in pops:
            key = f"{role}:{pop}"
            result[key] = {
                "placeholder_event": weighted_scores(weak_pairs("event", "placeholder_event", pop, role), [*EVENT_VOCAB]),
                "naive_bayes_event": weighted_scores(weak_pairs("event", "nb_event", pop, role), [*EVENT_VOCAB]),
                "placeholder_sentiment": weighted_scores(weak_pairs("sentiment", "placeholder_sentiment", pop, role), SENTIMENT_VOCAB),
                "naive_bayes_sentiment": weighted_scores(weak_pairs("sentiment", "nb_sentiment", pop, role), SENTIMENT_VOCAB)}
    out["weak_labels_vs_gold"] = result
    def wshare(pred, pop: str) -> float:
        tot = sum(items[g]["weight"] for g in lab if items[g]["population"] == pop)
        return round(sum(items[g]["weight"] for g, v in lab.items() if items[g]["population"] == pop and pred(v)) / tot, 3) if tot else float("nan")

    def wdist(key: str, pop: str) -> dict[str, float]:
        tot = sum(items[g]["weight"] for g in lab if items[g]["population"] == pop)
        d: dict[str, float] = defaultdict(float)
        for g, v in lab.items():
            if items[g]["population"] == pop:
                d[v[key]] += items[g]["weight"] / tot
        return {k: round(x, 3) for k, x in sorted(d.items())}

    out["gold_event_distribution_weighted"] = {pop: wdist("event", pop) for pop in ("history", "tfn")}
    out["history_population_estimates"] = {
        "n": sum(items[g]["population"] == "history" for g in lab),
        "share_none": wshare(lambda v: v["event"] == "NONE", "history"),
        "entity_ok_rate_among_resolved": round(
            sum(items[g]["weight"] for g, v in lab.items() if items[g]["population"] == "history" and v["entity_ok"] == "y")
            / max(1e-9, sum(items[g]["weight"] for g, v in lab.items() if items[g]["population"] == "history" and v["entity_ok"] in ("y", "n"))), 3),
        "sentiment_distribution": wdist("sentiment", "history"),
        "note": "inclusion-probability weighted over all history strata; the targeted strata make this approximate"}

    # ---- unweighted estimates from the exact simple-random strata (the unbiased, easy-to-explain numbers)
    rand: dict[str, dict[str, Any]] = {}
    for stratum in sorted({it["stratum"] for it in items.values() if it["stratum"].startswith("rand:")}):
        ids = [g for g in lab if items[g]["stratum"] == stratum]
        none = sum(lab[g]["event"] == "NONE" for g in ids)
        rand[stratum] = {"n": len(ids), "share_none": round(none / len(ids), 3) if ids else None, "none_ci95": wilson(none, len(ids)),
                         "event_counts": dict(sorted(Counter(lab[g]["event"] for g in ids).items())),
                         "sentiment_counts": dict(sorted(Counter(lab[g]["sentiment"] for g in ids).items())),
                         "entity_ok_share_of_resolved": round(sum(lab[g]["entity_ok"] == "y" for g in ids) / max(1, sum(lab[g]["entity_ok"] in ("y", "n") for g in ids)), 3)}
    out["random_strata"] = rand

    # ---- agreement: AI vs human overrides, and self-consistency
    if adjudication:
        rows = [r for r in adjudication if any(r.get(k, "").strip() for k in ("human_sentiment", "human_event_class", "human_entity_ok"))]
        ag: dict[str, Any] = {"rows_reviewed_by_human": len(rows)}
        for name, ai_k, hu_k in (("event", "ai_event_class", "human_event_class"), ("sentiment", "ai_sentiment", "human_sentiment"),
                                 ("entity_ok", "ai_entity_ok", "human_entity_ok")):
            pairs = [(r[ai_k].strip(), r[hu_k].strip()) for r in rows if r.get(hu_k, "").strip()]
            ag[name] = {"n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None,
                        "kappa": round(cohens_kappa([a for a, _ in pairs], [b for _, b in pairs]), 3) if pairs else None}
        out["ai_vs_human"] = ag
    if consistency:
        first = {r["gold_id"]: r for r in sheet}
        pairs_e = [(first[r["gold_id"]]["ai_event_class"].strip(), r["ai_event_class"].strip()) for r in consistency if r.get("ai_event_class", "").strip()]
        pairs_s = [(first[r["gold_id"]]["ai_sentiment"].strip(), r["ai_sentiment"].strip()) for r in consistency if r.get("ai_sentiment", "").strip()]
        out["self_consistency"] = {
            "note": "same annotator, second blind pass: an upper bound on label noise, NOT an independent inter-annotator kappa",
            "event": {"n": len(pairs_e), "agreement": round(sum(a == b for a, b in pairs_e) / max(1, len(pairs_e)), 3),
                      "kappa": round(cohens_kappa([a for a, _ in pairs_e], [b for _, b in pairs_e]), 3)},
            "sentiment": {"n": len(pairs_s), "agreement": round(sum(a == b for a, b in pairs_s) / max(1, len(pairs_s)), 3),
                          "kappa": round(cohens_kappa([a for a, _ in pairs_s], [b for _, b in pairs_s]), 3)}}
    return out


def adjudication_rows(sheet: Sequence[dict[str, str]], manifest: dict[str, Any], cfg: GoldConfig) -> list[dict[str, str]]:
    """Rows a human should look at: the AI label disagrees with the weak/mapped label (up to N-20), plus 20 random."""
    items = manifest["items"]
    labelled = [r for r in sheet if r.get("ai_event_class", "").strip()]

    def disagrees(r: dict[str, str]) -> bool:
        w = items[r["gold_id"]]["weak"]
        ref = w["mapped_class"] if items[r["gold_id"]]["population"] == "tfn" else w["placeholder_event"]
        return r["ai_event_class"].strip() != ref

    dis = sorted((r for r in labelled if disagrees(r)), key=lambda r: _h(cfg.seed, "adj:" + r["gold_id"]))
    rand = sorted(labelled, key=lambda r: _h(cfg.seed, "adjr:" + r["gold_id"]))
    k_rand = min(20, cfg.adjudication_rows)
    pick = dis[: max(0, cfg.adjudication_rows - k_rand)]
    have = {r["gold_id"] for r in pick}
    pick += [r for r in rand if r["gold_id"] not in have][:k_rand]
    return [{**{k: r.get(k, "") for k in ADJ_COLUMNS[:7]}, **{k: "" for k in ADJ_COLUMNS[7:]}} for r in sorted(pick, key=lambda r: r["gold_id"])]


def consistency_rows(sheet: Sequence[dict[str, str]], cfg: GoldConfig) -> list[dict[str, str]]:
    """A blind re-labelling sheet (no labels shown) for a seeded sample of already-labelled rows."""
    labelled = [r for r in sheet if r.get("ai_event_class", "").strip()]
    pick = sorted(labelled, key=lambda r: _h(cfg.seed, "cons:" + r["gold_id"]))[: cfg.consistency_rows]
    return [{**{k: r[k] for k in SHEET_COLUMNS[:5]}, **{k: "" for k in SHEET_COLUMNS[5:]}} for r in sorted(pick, key=lambda r: r["gold_id"])]
