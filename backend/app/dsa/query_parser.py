"""Advanced query parser: stacks + shunting-yard (LeetCode 20 / 224).

Users type queries like

    (transformer OR "state space") AND author:gu NOT title:survey

and we translate them into arXiv's grammar:

    (all:transformer OR all:"state space") AND au:gu ANDNOT ti:survey

Pipeline:
1. tokenize  (strings: quotes, field:term, parentheses)
2. shunting-yard with an operator stack -> postfix (also checks parentheses)
3. evaluate postfix with an operand stack -> arXiv string, parenthesized
Adjacent terms get an implicit AND. Precedence: NOT = AND > OR.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TOKENS = 64  # keeps upstream queries cheap

FIELDS = {
    "all": "all", "ti": "ti", "title": "ti", "au": "au", "author": "au",
    "abs": "abs", "abstract": "abs", "cat": "cat", "category": "cat",
    "co": "co", "comment": "co", "jr": "jr", "journal": "jr",
}
OPERATORS = {"AND": 2, "NOT": 2, "OR": 1}  # NOT is binary: a NOT b -> a ANDNOT b
_CATEGORY = re.compile(r"^[a-z\-]+(\.[A-Za-z\-]+|\.\*)?$")
_WORD = re.compile(r"^[\w\-\.\*']+$", re.UNICODE)


class QueryError(ValueError):
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message if position is None else f"{message} (at character {position + 1})")
        self.position = position


@dataclass(frozen=True)
class Token:
    kind: str  # "term" | "op" | "lparen" | "rparen"
    value: str
    pos: int


def _term(field: str, raw: str, pos: int) -> Token:
    if field == "cat":
        if not _CATEGORY.match(raw):
            raise QueryError(f"invalid category {raw!r}", pos)
        return Token("term", f"cat:{raw}", pos)
    if " " in raw:
        return Token("term", f'{field}:"{raw}"', pos)
    if not _WORD.match(raw):
        raise QueryError(f"unsupported characters in {raw!r}", pos)
    return Token("term", f"{field}:{raw}", pos)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(Token("lparen" if ch == "(" else "rparen", ch, i))
            i += 1
        elif ch == '"':
            end = text.find('"', i + 1)
            if end == -1:
                raise QueryError("unclosed quote", i)
            phrase = " ".join(text[i + 1:end].split())
            if not phrase:
                raise QueryError("empty quotes", i)
            tokens.append(_term("all", phrase, i))
            i = end + 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '()"':
                i += 1
            word = text[start:i]
            field, sep, rest = word.partition(":")
            if sep:  # field:term or field:"phrase"
                fld = FIELDS.get(field.lower())
                if fld is None:
                    raise QueryError(f"unknown field {field!r}", start)
                if not rest and i < n and text[i] == '"':
                    end = text.find('"', i + 1)
                    if end == -1:
                        raise QueryError("unclosed quote", i)
                    rest = " ".join(text[i + 1:end].split())
                    i = end + 1
                if not rest:
                    raise QueryError(f"nothing after {field}:", start)
                tokens.append(_term(fld, rest, start))
            elif word.upper() in OPERATORS:
                tokens.append(Token("op", word.upper(), start))
            else:
                tokens.append(_term("all", word, start))
        if len(tokens) > MAX_TOKENS:
            raise QueryError(f"query too long (max {MAX_TOKENS} tokens)")
    if not tokens:
        raise QueryError("empty query")
    return _with_implicit_and(tokens)


def _with_implicit_and(tokens: list[Token]) -> list[Token]:
    out: list[Token] = []
    for t in tokens:
        if out and out[-1].kind in ("term", "rparen") and t.kind in ("term", "lparen"):
            out.append(Token("op", "AND", t.pos))
        out.append(t)
    return out


def to_postfix(tokens: list[Token]) -> list[Token]:
    """Shunting-yard. The operator stack also validates parentheses (LC 20)."""
    output: list[Token] = []
    ops: list[Token] = []  # stack
    expect_operand = True
    for t in tokens:
        if t.kind == "term":
            if not expect_operand:
                raise QueryError("missing operator", t.pos)
            output.append(t)
            expect_operand = False
        elif t.kind == "lparen":
            if not expect_operand:
                raise QueryError("missing operator before '('", t.pos)
            ops.append(t)
        elif t.kind == "rparen":
            if expect_operand:
                raise QueryError("expected a term before ')'", t.pos)
            while ops and ops[-1].kind != "lparen":
                output.append(ops.pop())
            if not ops:
                raise QueryError("unmatched ')'", t.pos)
            ops.pop()  # discard '('
        else:  # operator
            if expect_operand:
                hint = " (NOT needs a term before it: try 'x NOT y')" if t.value == "NOT" else ""
                raise QueryError(f"{t.value} is missing its left side{hint}", t.pos)
            while ops and ops[-1].kind == "op" and OPERATORS[ops[-1].value] >= OPERATORS[t.value]:
                output.append(ops.pop())
            ops.append(t)
            expect_operand = True
    if expect_operand:
        raise QueryError("query ends with an operator", tokens[-1].pos)
    while ops:
        t = ops.pop()
        if t.kind == "lparen":
            raise QueryError("unmatched '('", t.pos)
        output.append(t)
    return output


def to_arxiv(postfix: list[Token]) -> str:
    """Evaluate postfix with an operand stack, emitting arXiv syntax."""
    stack: list[tuple[str, bool]] = []  # (text, is_compound)
    for t in postfix:
        if t.kind == "term":
            stack.append((t.value, False))
            continue
        (right, rc), (left, lc) = stack.pop(), stack.pop()
        op = "ANDNOT" if t.value == "NOT" else t.value
        wrap = lambda s, c: f"({s})" if c else s  # noqa: E731
        stack.append((f"{wrap(left, lc)} {op} {wrap(right, rc)}", True))
    return stack[0][0]


def parse_query(text: str) -> str:
    return to_arxiv(to_postfix(tokenize(text)))
