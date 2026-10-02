from __future__ import annotations

from eventshock.domain import DedupRelation, SourceType, TimestampOrigin
from eventshock.pipeline.dedup import Item, cluster_items
from tests.pipe_helpers import CFG, doc

D = CFG.dedup
AAPL = "ENT_AAPL"


def item(did, headline, *, entity=AAPL, origin=TimestampOrigin.GDELT_FIRST_SEEN, **kw):
    return Item.build(doc(did, headline, origin=origin.value, **kw), entity, origin)


def clusters(*items):
    return cluster_items(list(items), D)


def relations(cl):
    return sorted(m.relation.value for m in [*cl.members, *cl.exact])


class TestRelations:
    def test_same_url_is_exact_duplicate(self):
        a = item("a", "Apple unveils iPhone 18 at event", url="https://x.com/p?utm_source=a", hours=5)
        b = item("b", "Totally different words entirely", url="https://www.x.com/p/", hours=4, source="x.com")
        cl, = clusters(a, b)
        assert relations(cl) == ["EXACT_DUPLICATE"] and cl.canonical is a

    def test_same_text_same_outlet_exact_other_outlet_syndicated(self):
        a = item("a", "Apple raises dividend", source="a.com", hours=6)
        b = item("b", "Apple raises dividend - Reuters", source="a.com", hours=5)
        c = item("c", "APPLE RAISES DIVIDEND", source="b.com", hours=4)
        cl, = clusters(a, b, c)
        assert relations(cl) == ["EXACT_DUPLICATE", "SYNDICATED"]
        assert cl.domains == {"a.com", "b.com"} and len(cl.reports) == 2

    def test_near_duplicate(self):
        a = item("a", "Apple unveils new iPhone 18 lineup at September event", source="a.com", hours=6)
        b = item("b", "Apple unveils new iPhone 18 lineup at September event today", source="b.com", hours=5)
        cl, = clusters(a, b)
        assert relations(cl) == ["NEAR_DUPLICATE"]

    def test_same_event_needs_overlap_time_and_trusted_clock(self):
        a = item("a", "Apple unveils iPhone 18 at event", source="a.com", hours=6)
        b = item("b", "Apple unveils iPhone 18 lineup", source="b.com", hours=5)
        cl, = clusters(a, b)
        assert relations(cl) == ["SAME_EVENT"]
        far = item("c", "Apple unveils iPhone 18 lineup", source="c.com", hours=6 + 60)
        assert len(clusters(a, far)) == 2  # beyond the 48 h same-event window
        syn = item("d", "Apple unveils iPhone 18 lineup", source="d.com", hours=5,
                   origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK)
        assert len(clusters(a, syn)) == 2  # synthetic clocks are never used to correlate events

    def test_opposite_stories_with_low_overlap_stay_apart(self):
        a = item("a", "Apple stock rises after earnings beat", hours=6)
        b = item("b", "Apple faces antitrust probe in Europe", hours=5, source="b.com")
        assert len(clusters(a, b)) == 2


class TestClusterRules:
    def test_never_merge_across_entities(self):
        a = item("a", "Shares rise after earnings beat estimates", entity="ENT_AAPL", source="a.com")
        b = item("b", "Shares rise after earnings beat estimates", entity="ENT_MSFT", source="b.com")
        assert len(clusters(a, b)) == 2

    def test_unknown_entity_only_merges_on_text_duplicates_not_same_event(self):
        a = item("a", "Central banks signal caution on rate path", entity="UNKNOWN_ENTITY", source="a.com", hours=6)
        b = item("b", "Central banks signal caution on rate outlook", entity="UNKNOWN_ENTITY", source="b.com", hours=5)
        assert len(clusters(a, b)) == 2

    def test_star_clustering_prevents_chaining(self):
        a = item("a", "alpha beta gamma delta epsilon zeta", source="a.com", hours=9)
        b = item("b", "alpha beta gamma delta epsilon theta", source="b.com", hours=8)   # ~0.71 vs a
        c = item("c", "alpha beta gamma delta kappa theta", source="c.com", hours=7)     # ~0.67 vs b, 0.43 vs a
        out = clusters(a, b, c)
        assert [len(cl.reports) for cl in out] == [2, 1]

    def test_old_identical_headline_outside_window_is_a_new_story(self):
        a = item("a", "Stock market today: indexes edge higher", source="a.com", hours=24 * 10)
        b = item("b", "Stock market today: indexes edge higher", source="b.com", hours=2)
        assert len(clusters(a, b)) == 2

    def test_order_independent(self):
        items = [item(f"d{i}", f"Apple headline number {i % 3} alpha beta gamma", source=f"s{i % 4}.com", hours=30 - i)
                 for i in range(12)]
        fwd = [(c.canonical.doc.id, len(c.reports), len(c.exact)) for c in clusters(*items)]
        rev = [(c.canonical.doc.id, len(c.reports), len(c.exact)) for c in clusters(*reversed(items))]
        assert fwd == rev

    def test_social_duplicates_share_a_pseudo_domain(self):
        a = item("t1", "$AAPL - Oppenheimer upgrades Apple https://t.co/aaa", source="Twitter Financial News", url=None,
                 stype=SourceType.SOCIAL, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK, hours=100)
        b = item("t2", "$AAPL - Oppenheimer upgrades Apple https://t.co/bbb", source="Twitter Financial News", url=None,
                 stype=SourceType.SOCIAL, origin=TimestampOrigin.SYNTHETIC_REPLAY_CLOCK, hours=5)
        cl, = clusters(a, b)
        assert relations(cl) == ["EXACT_DUPLICATE"] and len(cl.reports) == 1
        assert DedupRelation.EXACT_DUPLICATE


def test_same_url_in_two_sources_is_one_story_with_a_stable_canonical_whatever_the_input_order():
    a = item("gdelt-x", "Apple raises dividend", source="a.com", hours=5, url="https://a.com/p")
    b = item("gkg-x", "Apple raises dividend", source="a.com", hours=5, url="https://a.com/p")
    a.doc.raw_metadata["adapter"], b.doc.raw_metadata["adapter"] = "gdelt-doc", "gdelt-gkg"
    first = [(c.canonical.doc.id, len(c.exact)) for c in clusters(a, b)]
    second = [(c.canonical.doc.id, len(c.exact)) for c in clusters(b, a)]
    assert first == second == [("gdelt-x", 1)]


def _exhaustive(items, cfg):
    """The original O(n x clusters) algorithm, kept as the reference for the indexed implementation."""
    from eventshock.pipeline.dedup import Cluster, Member, relate

    clusters, by_entity = [], {}
    for it in sorted(items, key=lambda i: i.sort_key):
        for cl in by_entity.get(it.entity_id, []):
            rel = relate(cl.canonical, it, cfg)
            if rel is None:
                continue
            (cl.exact if rel[0] is DedupRelation.EXACT_DUPLICATE else cl.members).append(Member(it, rel[0], round(rel[1], 4)))
            break
        else:
            cl = Cluster(it)
            clusters.append(cl)
            by_entity.setdefault(it.entity_id, []).append(cl)
    return clusters


def test_indexed_clustering_equals_the_exhaustive_scan_on_random_data():
    import random

    rng = random.Random(11)
    vocab = [f"w{i}" for i in range(40)]
    items = []
    for i in range(400):
        words = rng.sample(vocab, rng.randint(1, 9))
        items.append(item(f"d{i}", " ".join(words), entity=rng.choice([AAPL, "ENT_MSFT", "UNKNOWN_ENTITY"]),
                          source=rng.choice(["a.com", "b.com", "c.com"]), hours=rng.uniform(1, 200),
                          url=rng.choice(["auto", "auto", f"https://x.com/{i % 25}"])))
    sig = lambda cls: [(c.canonical.doc.id, sorted(m.item.doc.id for m in c.members), sorted(m.item.doc.id for m in c.exact)) for c in cls]  # noqa: E731
    assert sig(cluster_items(items, D)) == sig(_exhaustive(items, D))
