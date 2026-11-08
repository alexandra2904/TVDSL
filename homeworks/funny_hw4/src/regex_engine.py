from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque
from typing import Optional


EPS = None


class RegexSyntaxError(ValueError):
    pass


@dataclass
class Fragment:
    start: int
    end: int


class NFA:
    def __init__(self):
        self.next_state = 0
        self.eps = defaultdict(set)
        self.trans = defaultdict(lambda: defaultdict(set))
        self.accepts = {}  

    def new_state(self):
        s = self.next_state
        self.next_state += 1
        return s


class RegexParser:

    def __init__(self, pattern: str, alphabet: set[int]):
        self.pattern = pattern
        self.pos = 0
        self.alphabet = alphabet

    def peek(self, ch):
        return self.pos < len(self.pattern) and self.pattern[self.pos] == ch

    def parse(self):
        if not self.pattern:
            raise RegexSyntaxError("empty regular expression")
        result = self.parse_alt()
        if self.pos != len(self.pattern):
            raise RegexSyntaxError(
                f"unexpected character {self.pattern[self.pos]!r} at {self.pos}"
            )
        return result

    def parse_alt(self):
        left = self.parse_concat()
        while self.peek("|"):
            self.pos += 1
            right = self.parse_concat()
            left = ("alt", left, right)
        return left

    def parse_concat(self):
        parts = []
        while self.pos < len(self.pattern) and self.pattern[self.pos] not in ")|":
            parts.append(self.parse_repeat())
        if not parts:
            return ("empty",)
        result = parts[0]
        for part in parts[1:]:
            result = ("concat", result, part)
        return result

    def parse_repeat(self):
        node = self.parse_atom()
        while self.pos < len(self.pattern) and self.pattern[self.pos] in "*+?":
            op = self.pattern[self.pos]
            self.pos += 1
            node = (op, node)
        return node

    def parse_atom(self):
        if self.peek("("):
            self.pos += 1
            node = self.parse_alt()
            if not self.peek(")"):
                raise RegexSyntaxError("missing ')'")
            self.pos += 1
            return node

        if self.peek("["):
            return self.parse_class()

        if self.pos >= len(self.pattern):
            raise RegexSyntaxError("unexpected end of regex")

        return ("char", self.parse_escape())

    def parse_escape(self):
        ch = self.pattern[self.pos]
        self.pos += 1
        if ch != "\\":
            return ord(ch)

        if self.pos >= len(self.pattern):
            raise RegexSyntaxError("dangling backslash")

        ch = self.pattern[self.pos]
        self.pos += 1
        mapping = {"t": 9, "r": 13, "n": 10, "s": 32, "d": None}
        if ch == "d":
            return ("class", set(range(ord("0"), ord("9") + 1)))
        if ch in mapping:
            return mapping[ch]
        return ord(ch)

    def parse_class(self):
        self.pos += 1
        if self.pos >= len(self.pattern):
            raise RegexSyntaxError("unterminated character class")

        negated = False
        if self.pattern[self.pos] == "^":
            negated = True
            self.pos += 1

        chars = set()
        first = True
        while self.pos < len(self.pattern) and self.pattern[self.pos] != "]":
            start = self.parse_class_char()
            if (
                self.pos + 0 < len(self.pattern)
                and self.pattern[self.pos] == "-"
                and self.pos + 1 < len(self.pattern)
                and self.pattern[self.pos + 1] != "]"
            ):
                self.pos += 1
                end = self.parse_class_char()
                if isinstance(start, tuple) or isinstance(end, tuple):
                    raise RegexSyntaxError("range endpoints must be single characters")
                if start > end:
                    raise RegexSyntaxError("invalid character range")
                chars.update(range(start, end + 1))
            else:
                if isinstance(start, tuple):
                    chars.update(start[1])
                else:
                    chars.add(start)
            first = False

        if self.pos >= len(self.pattern) or self.pattern[self.pos] != "]":
            raise RegexSyntaxError("unterminated character class")
        self.pos += 1

        if negated:
            chars = set(self.alphabet) - chars

        if not chars:
            raise RegexSyntaxError("empty character class")
        return ("class", chars)

    def parse_class_char(self):
        if self.pos >= len(self.pattern):
            raise RegexSyntaxError("unterminated character class")
        ch = self.pattern[self.pos]
        self.pos += 1
        if ch != "\\":
            return ord(ch)
        if self.pos >= len(self.pattern):
            raise RegexSyntaxError("dangling backslash")
        ch = self.pattern[self.pos]
        self.pos += 1
        if ch == "d":
            return ("class", set(range(ord("0"), ord("9") + 1)))
        mapping = {"t": 9, "r": 13, "n": 10, "s": 32}
        return mapping.get(ch, ord(ch))


class ThompsonBuilder:
    def __init__(self, alphabet: set[int]):
        self.nfa = NFA()
        self.alphabet = alphabet

    def build_node(self, node) -> Fragment:
        kind = node[0]

        if kind == "empty":
            s, e = self.nfa.new_state(), self.nfa.new_state()
            self.nfa.eps[s].add(e)
            return Fragment(s, e)

        if kind == "char":
            value = node[1]
            if isinstance(value, tuple):
                return self.build_set(value[1])
            s, e = self.nfa.new_state(), self.nfa.new_state()
            self.nfa.trans[s][value].add(e)
            return Fragment(s, e)

        if kind == "class":
            return self.build_set(node[1])

        if kind == "concat":
            a = self.build_node(node[1])
            b = self.build_node(node[2])
            self.nfa.eps[a.end].add(b.start)
            return Fragment(a.start, b.end)

        if kind == "alt":
            s, e = self.nfa.new_state(), self.nfa.new_state()
            a = self.build_node(node[1])
            b = self.build_node(node[2])
            self.nfa.eps[s].update((a.start, b.start))
            self.nfa.eps[a.end].add(e)
            self.nfa.eps[b.end].add(e)
            return Fragment(s, e)

        if kind == "*":
            s, e = self.nfa.new_state(), self.nfa.new_state()
            a = self.build_node(node[1])
            self.nfa.eps[s].update((a.start, e))
            self.nfa.eps[a.end].update((a.start, e))
            return Fragment(s, e)

        if kind == "+":
            s, e = self.nfa.new_state(), self.nfa.new_state()
            a = self.build_node(node[1])
            self.nfa.eps[s].add(a.start)
            self.nfa.eps[a.end].update((a.start, e))
            return Fragment(s, e)

        if kind == "?":
            s, e = self.nfa.new_state(), self.nfa.new_state()
            a = self.build_node(node[1])
            self.nfa.eps[s].update((a.start, e))
            self.nfa.eps[a.end].add(e)
            return Fragment(s, e)

        raise RegexSyntaxError(f"unknown AST node: {kind}")

    def build_set(self, values):
        s, e = self.nfa.new_state(), self.nfa.new_state()
        for ch in values:
            self.nfa.trans[s][ch].add(e)
        return Fragment(s, e)

    def add_regex(self, pattern: str, token_index: int):
        ast = RegexParser(pattern, self.alphabet).parse()
        fragment = self.build_node(ast)
        self.nfa.accepts[fragment.end] = token_index
        return fragment.start, fragment.end


def epsilon_closure(nfa: NFA, states):
    result = set(states)
    stack = list(result)
    while stack:
        state = stack.pop()
        for nxt in nfa.eps[state]:
            if nxt not in result:
                result.add(nxt)
                stack.append(nxt)
    return frozenset(result)


def move(nfa: NFA, states, symbol: int):
    result = set()
    for state in states:
        result.update(nfa.trans[state].get(symbol, ()))
    return result


@dataclass
class DFA:
    transitions: list[list[int]]
    accepting: dict[int, int]
    start: int
    trap: int
    alphabet: list[int]


def nfa_to_dfa(nfa: NFA, starts, alphabet: list[int]) -> DFA:
    start_set = epsilon_closure(nfa, starts)
    ids = {start_set: 0}
    subsets = [start_set]
    transitions = []

    i = 0
    while i < len(subsets):
        current = subsets[i]
        row = []
        for symbol in alphabet:
            target = epsilon_closure(nfa, move(nfa, current, symbol))
            if target not in ids:
                ids[target] = len(subsets)
                subsets.append(target)
            row.append(ids[target])
        transitions.append(row)
        i += 1

    trap_set = frozenset()
    if trap_set not in ids:
        ids[trap_set] = len(subsets)
        subsets.append(trap_set)
        transitions.append([ids[trap_set]] * len(alphabet))

    trap = ids[trap_set]

    for row in transitions:
        for j, target in enumerate(row):
            if target == ids[trap_set]:
                row[j] = trap
    while len(transitions) < len(subsets):
        transitions.append([trap] * len(alphabet))

    accepting = {}
    for subset, state_id in ids.items():
        candidates = [
            nfa.accepts[s] for s in subset if s in nfa.accepts
        ]
        if candidates:
            accepting[state_id] = min(candidates)

    return DFA(transitions, accepting, 0, trap, alphabet)


def minimize_hopcroft(dfa: DFA) -> DFA:
    n = len(dfa.transitions)
    alphabet = dfa.alphabet

    accepting_states = set(dfa.accepting)
    nonaccepting = set(range(n)) - accepting_states

    label_groups = defaultdict(set)
    for state in accepting_states:
        label_groups[dfa.accepting[state]].add(state)

    partitions = [set(group) for group in label_groups.values()]
    if nonaccepting:
        partitions.append(nonaccepting)

    partitions = [p for p in partitions if p]
    state_to_block = {}
    for idx, block in enumerate(partitions):
        for state in block:
            state_to_block[state] = idx

    work = deque(range(len(partitions)))

    while work:
        a_idx = work.popleft()
        A = partitions[a_idx]

        for symbol_index in range(len(alphabet)):
            X = {
                state
                for state in range(n)
                if dfa.transitions[state][symbol_index] in A
            }

            affected = []
            for y_idx, Y in enumerate(partitions):
                inter = Y & X
                diff = Y - X
                if inter and diff:
                    affected.append((y_idx, inter, diff))

            for y_idx, inter, diff in affected:
                partitions[y_idx] = inter
                new_idx = len(partitions)
                partitions.append(diff)

                for state in inter:
                    state_to_block[state] = y_idx
                for state in diff:
                    state_to_block[state] = new_idx

                try:
                    work.remove(y_idx)
                    work.append(y_idx)
                    work.append(new_idx)
                except ValueError:
                    if len(inter) <= len(diff):
                        work.append(y_idx)
                    else:
                        work.append(new_idx)

    start_block = state_to_block[dfa.start]
    ordered_blocks = [start_block] + sorted(
        [i for i in range(len(partitions)) if i != start_block],
        key=lambda i: min(partitions[i])
    )
    block_to_new = {block: i for i, block in enumerate(ordered_blocks)}

    new_transitions = []
    new_accepting = {}
    for block in ordered_blocks:
        representative = min(partitions[block])
        new_transitions.append([
            block_to_new[state_to_block[target]]
            for target in dfa.transitions[representative]
        ])
        labels = {dfa.accepting[s] for s in partitions[block] if s in dfa.accepting}
        if labels:
            new_accepting[block_to_new[block]] = min(labels)

    new_trap = block_to_new[state_to_block[dfa.trap]]
    return DFA(
        new_transitions,
        new_accepting,
        block_to_new[start_block],
        new_trap,
        alphabet,
    )
