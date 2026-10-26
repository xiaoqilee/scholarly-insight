"""Each data structure is checked on edge cases and against a brute-force oracle."""
import random
import re
from collections import Counter, OrderedDict, deque

import pytest

from app.dsa.edit_distance import within_distance
from app.dsa.lru import LRUCache
from app.dsa.query_parser import QueryError, parse_query
from app.dsa.rate_window import SlidingWindowLimiter
from app.dsa.search import first_not_newer
from app.dsa.topk import top_k
from app.dsa.trie import Trie
from app.suggest import SuggestIndex, title_terms

rng = random.Random(42)


# ---------------------------------------------------------------- LRU (hash map + linked list)

class TestLRU:
    def test_leetcode_146_example(self):
        c = LRUCache(2)
        c.put(1, 1); c.put(2, 2)
        assert c.get(1) == 1
        c.put(3, 3)                      # evicts 2
        assert c.get(2) is None
        c.put(4, 4)                      # evicts 1
        assert (c.get(1), c.get(3), c.get(4)) == (None, 3, 4)
        assert c.evictions == 2

    def test_update_moves_to_front(self):
        c = LRUCache(2)
        c.put("a", 1); c.put("b", 2); c.put("a", 9); c.put("c", 3)
        assert list(c.keys()) == ["c", "a"] and c.get("a") == 9

    def test_capacity_one(self):
        c = LRUCache(1)
        c.put(1, 1); c.put(2, 2)
        assert c.get(1) is None and c.get(2) == 2 and len(c) == 1

    def test_rejects_zero_capacity(self):
        with pytest.raises(ValueError):
            LRUCache(0)

    def test_matches_ordereddict_oracle(self):
        c, oracle, cap = LRUCache(8), OrderedDict(), 8
        for _ in range(5000):
            k = rng.randrange(20)
            if rng.random() < 0.5:
                got = c.get(k)
                want = oracle.get(k)
                if k in oracle:
                    oracle.move_to_end(k)
                assert got == want
            else:
                v = rng.randrange(1000)
                c.put(k, v)
                oracle[k] = v
                oracle.move_to_end(k)
                if len(oracle) > cap:
                    oracle.popitem(last=False)
            assert list(c.keys()) == list(reversed(oracle))


# ---------------------------------------------------------------- Trie

class TestTrie:
    def test_prefix_ranking(self):
        t = Trie()
        for word, n in [("transformer", 5), ("transfer", 3), ("transport", 1), ("tree", 4)]:
            t.add(word, weight=n)
        assert t.top_k("tran") == [("transformer", 5), ("transfer", 3), ("transport", 1)]
        assert t.top_k("tr", 2) == [("transformer", 5), ("tree", 4)]
        assert t.top_k("x") == [] and t.top_k("transformers") == []

    def test_one_display_many_keys_counted_once(self):
        t = Trie()
        t.add("Yann LeCun", ["yann lecun", "lecun"])
        t.add("Yann LeCun", ["yann lecun", "lecun"])
        assert t.top_k("lec") == [("Yann LeCun", 2)] and t.top_k("yann") == [("Yann LeCun", 2)]

    def test_accents_and_case_normalized(self):
        t = Trie()
        t.add("Erwin Schrödinger", ["schrodinger"])
        assert t.top_k("SCHRÖ") == [("Erwin Schrödinger", 1)]

    def test_late_riser_enters_full_topk(self):
        t = Trie(k_max=2)
        t.add("aa", weight=5); t.add("ab", weight=4); t.add("ac", weight=1)
        assert [d for d, _ in t.top_k("a")] == ["aa", "ab"]
        t.add("ac", weight=10)
        assert [d for d, _ in t.top_k("a")] == ["ac", "aa"]

    def test_matches_brute_force(self):
        t, counts = Trie(k_max=5), Counter()
        words = ["".join(rng.choice("abc") for _ in range(rng.randint(1, 5))) for _ in range(60)]
        for _ in range(400):
            w = rng.choice(words)
            n = rng.randint(1, 3)
            t.add(w, weight=n)
            counts[w] += n
        for prefix in ["", "a", "ab", "b", "ca", "abc", "ccc"]:
            want = sorted((w for w in counts if w.startswith(prefix)), key=lambda w: (-counts[w], w))[:5]
            assert [d for d, _ in t.top_k(prefix, 5)] == want


class TestSuggestIndex:
    def test_authors_terms_categories(self):
        ix = SuggestIndex()
        ix.add_article("Attention Is All You Need", ["Ashish Vaswani", "Noam Shazeer"], "cs.CL")
        ix.add_article("Attention for Graphs", ["Ashish Vaswani"], "cs.LG")
        assert ix.suggest("author", "vas")["suggestions"][0] == {"text": "Ashish Vaswani", "count": 2}
        assert ix.suggest("term", "att")["suggestions"][0]["text"] == "attention"
        cat = ix.suggest("category", "machine")["suggestions"][0]
        assert cat["text"] in {"cs.LG", "stat.ML"} and cat["label"].endswith("Machine Learning")

    def test_did_you_mean(self):
        ix = SuggestIndex()
        ix.add_article("x", ["Yann LeCun"], None)
        out = ix.suggest("author", "lecnu")
        assert out["suggestions"] == [] and out["did_you_mean"][0]["text"] == "Yann LeCun"

    def test_title_terms_drop_stopwords(self):
        assert title_terms("A Survey of the State-Space Models") == {"survey", "state-space", "models"}


# ---------------------------------------------------------------- Stack: query parser

class TestQueryParser:
    @pytest.mark.parametrize("text,want", [
        ("transformer", "all:transformer"),
        ("graph neural", "all:graph AND all:neural"),                        # implicit AND
        ('"graph neural network"', 'all:"graph neural network"'),
        ("author:lecun title:cnn", "au:lecun AND ti:cnn"),
        ('au:"yann lecun"', 'au:"yann lecun"'),
        ("a OR b AND c", "all:a OR (all:b AND all:c)"),                      # precedence
        ("(a OR b) AND c", "(all:a OR all:b) AND all:c"),
        ("a NOT b", "all:a ANDNOT all:b"),
        ("(transformer OR \"state space\") AND author:gu NOT title:survey",
         '((all:transformer OR all:"state space") AND au:gu) ANDNOT ti:survey'),
        ("cat:cs.LG OR cat:stat.ML", "cat:cs.LG OR cat:stat.ML"),
        ("((a))", "all:a"),
        ("a or b", "all:a OR all:b"),                                       # case-insensitive ops
    ])
    def test_translation(self, text, want):
        assert parse_query(text) == want

    @pytest.mark.parametrize("text,msg", [
        ("(a OR b", "unmatched '('"),
        ("a OR b)", "unmatched ')'"),
        ("a AND", "ends with an operator"),
        ("OR a", "missing its left side"),
        ("NOT a", "NOT needs a term"),
        ("()", "expected a term"),
        ('"unclosed', "unclosed quote"),
        ("venue:x", "unknown field"),
        ("cat:cs.DB;DROP", "invalid category"),
        ("a AND OR b", "missing its left side"),
        ("", "empty query"),
    ])
    def test_errors(self, text, msg):
        with pytest.raises(QueryError, match=re.escape(msg)):
            parse_query(text)

    def test_balanced_paren_fuzz(self):
        """Random strings of terms/ops/parens: parser agrees with a stack balance check (LC 20)."""
        for _ in range(500):
            toks = [rng.choice(["a", "b", "(", ")", "AND", "OR"]) for _ in range(rng.randint(1, 8))]
            depth, balanced = 0, True
            for t in toks:
                depth += t == "("
                depth -= t == ")"
                balanced &= depth >= 0
            balanced &= depth == 0
            try:
                parse_query(" ".join(toks))
            except QueryError as e:
                if "unmatched" in str(e):
                    assert not balanced, toks
                continue
            assert balanced, toks

    def test_token_limit(self):
        with pytest.raises(QueryError, match="too long"):
            parse_query(" ".join(["a"] * 70))


# ---------------------------------------------------------------- Queue: sliding window

class TestSlidingWindow:
    def test_leetcode_933_shape(self):
        lim = SlidingWindowLimiter(limit=3, window_s=10)
        assert [lim.check("ip", t)[0] for t in (0, 1, 2, 3)] == [True, True, True, False]
        allowed, retry = lim.check("ip", 5)
        assert not allowed and retry == pytest.approx(5)
        assert lim.check("ip", 10.5)[0]          # t=0 left the window
        assert lim.check("other", 3)[0]          # clients are independent

    def test_matches_brute_force(self):
        lim, log = SlidingWindowLimiter(limit=5, window_s=3), []
        t = 0.0
        for _ in range(2000):
            t += rng.random()
            recent = [x for x in log if x > t - 3]
            want = len(recent) < 5
            assert lim.check("c", t)[0] == want
            if want:
                log.append(t)

    def test_prunes_idle_clients(self):
        lim = SlidingWindowLimiter(limit=1, window_s=1, max_clients=10)
        for i in range(10):
            lim.check(f"c{i}", 0)
        lim.check("new", 5)
        assert len(lim) == 1


# ---------------------------------------------------------------- Binary search

class TestBinarySearch:
    def test_edges(self):
        d = [50, 40, 40, 30, 10]
        assert first_not_newer(d, 60) == 0
        assert first_not_newer(d, 40) == 1     # equal is not newer
        assert first_not_newer(d, 35) == 3
        assert first_not_newer(d, 0) == 5
        assert first_not_newer([], 5) == 0

    def test_matches_linear_scan(self):
        for _ in range(500):
            d = sorted((rng.randint(0, 50) for _ in range(rng.randint(0, 30))), reverse=True)
            x = rng.randint(-5, 55)
            assert first_not_newer(d, x) == sum(v > x for v in d)


# ---------------------------------------------------------------- Heap top-k

class TestTopK:
    def test_basic_and_ties(self):
        c = {"cs.LG": 9, "cs.DB": 4, "cs.CV": 4, "quant-ph": 1}
        assert top_k(c, 3) == [("cs.LG", 9), ("cs.CV", 4), ("cs.DB", 4)]
        assert top_k(c, 0) == [] and top_k({}, 3) == []
        assert len(top_k(c, 10)) == 4

    def test_matches_sort(self):
        for _ in range(300):
            c = {f"q{i}": rng.randint(0, 20) for i in range(rng.randint(0, 40))}
            k = rng.randint(1, 10)
            want = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
            assert top_k(c, k) == want


# ---------------------------------------------------------------- DP edit distance

def _full_dp(a, b):
    """Unbanded optimal-string-alignment distance, full table."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


class TestEditDistance:
    def test_adjacent_swap_is_one_edit(self):
        assert within_distance("lecnu", "lecun", 1) == 1
        assert within_distance("ab", "ba", 1) == 1

    def test_leetcode_72_examples(self):
        assert within_distance("horse", "ros", 3) == 3
        assert within_distance("intention", "execution", 5) == 5
        assert within_distance("intention", "execution", 4) is None

    def test_matches_full_dp(self):
        for _ in range(1000):
            a = "".join(rng.choice("abc") for _ in range(rng.randint(0, 7)))
            b = "".join(rng.choice("abc") for _ in range(rng.randint(0, 7)))
            d, k = _full_dp(a, b), rng.randint(0, 3)
            assert within_distance(a, b, k) == (d if d <= k else None), (a, b, k)
