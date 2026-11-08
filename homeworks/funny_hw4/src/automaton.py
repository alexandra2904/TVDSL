from __future__ import annotations

import json
from pathlib import Path

from regex_engine import ThompsonBuilder, nfa_to_dfa, minimize_hopcroft


def build_automata(token_specs):
    alphabet = list(range(128))
    builder = ThompsonBuilder(set(alphabet))

    starts = []
    for index, token in enumerate(token_specs):
        start, _ = builder.add_regex(token["regex"], index)
        starts.append(start)

    common_start = builder.nfa.new_state()
    for start in starts:
        builder.nfa.eps[common_start].add(start)

    dfa = nfa_to_dfa(builder.nfa, [common_start], alphabet)
    minimized = minimize_hopcroft(dfa)
    return builder.nfa, dfa, minimized


def serialize_dfa(dfa, token_specs):
    symbols = [chr(i) for i in dfa.alphabet]
    return {
        "alphabet": "ASCII",
        "alphabet_size": len(dfa.alphabet),
        "start_state": dfa.start,
        "trap_state": dfa.trap,
        "state_count": len(dfa.transitions),
        "accepting": {
            str(state): {
                "token": token_specs[token_index]["name"],
                "priority": token_index,
                "skip": token_specs[token_index]["skip"],
            }
            for state, token_index in sorted(dfa.accepting.items())
        },
        "symbols": symbols,
        "transitions": dfa.transitions,
    }


def save_dfa(path: Path, dfa, token_specs):
    path.write_text(
        json.dumps(serialize_dfa(dfa, token_specs), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
