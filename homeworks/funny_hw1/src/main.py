from __future__ import annotations

import argparse
import json 
import sys
from pathlib import Path

from automaton import build_automata, save_dfa 
from lexer import Lexer, LexerError 


ROOT = Path(__file__).resolve().parents[1]
TOKENS_FILE = ROOT / "tokens.json"
OUTPUT_DIR = ROOT / "output"
TEST_FILE = ROOT / "tests" / "lexer_tests.json"


def load_specs(): 
    data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    return data["tokens"]


def load_minimized(specs): 
    from automaton import build_automata
    _, _, minimized = build_automata(specs)
    return minimized


def build_command():
    specs = load_specs()
    nfa, dfa, minimized = build_automata(specs)

    OUTPUT_DIR.mkdir(exist_ok=True)
    save_dfa(OUTPUT_DIR / "dfa.json", dfa, specs)
    save_dfa(OUTPUT_DIR / "minimized_dfa.json", minimized, specs)

    stats = {
        "nfa_states": nfa.next_state,
        "dfa_states_before_minimization": len(dfa.transitions),
        "dfa_states_after_minimization": len(minimized.transitions),
        "alphabet_size": len(minimized.alphabet),
        "trap_state": minimized.trap,
        "token_count": len(specs),
    }
    (OUTPUT_DIR / "stats.json").write_text(
        json.dumps(stats, indent=2),
        encoding="utf-8",
    )

    print("Build completed.")
    print(f"NFA states: {stats['nfa_states']}")
    print(f"DFA states before minimization: {stats['dfa_states_before_minimization']}")
    print(f"DFA states after minimization:  {stats['dfa_states_after_minimization']}")
    print(f"Alphabet: ASCII ({stats['alphabet_size']} symbols)")
    print(f"Trap state: {stats['trap_state']}")
    print(f"Output: {OUTPUT_DIR}")


def make_lexer(): 
    specs = load_specs()
    _, _, minimized = build_automata(specs) 
    return Lexer(minimized, specs) 

def test_command():
    lexer = make_lexer()
    tests = json.loads(TEST_FILE.read_text(encoding="utf-8"))["tests"]

    passed = 0
    for case in tests:
        kind = case["kind"]
        text = case["input"]

        try:
            if kind == "token":
                actual = lexer.accept_whole_token(text)
                expected = case.get("expected_token")
                ok = actual == expected
                actual_text = actual if actual is not None else "ERROR"
            elif kind == "source":
                actual_tokens = [t.as_dict() for t in lexer.tokenize(text)]
                expected = case.get("expected_tokens", [])
                ok = [
                    {"token": x["token"], "lexeme": x["lexeme"]}
                    for x in actual_tokens
                ] == expected
                actual_text = actual_tokens
            elif kind == "error":
                try:
                    lexer.tokenize(text)
                    ok = False
                    actual_text = "NO_ERROR"
                except LexerError as exc:
                    ok = True
                    actual_text = f"ERROR: {exc}"
            else:
                raise ValueError(f"unknown test kind: {kind}")
        except Exception as exc:
            ok = False
            actual_text = f"EXCEPTION: {type(exc).__name__}: {exc}"

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['name']}")
        if not ok:
            print(f"       expected: {case.get('expected_token', case.get('expected_tokens'))}")
            print(f"       actual:   {actual_text}")
        passed += int(ok)

    print(f"\n{passed}/{len(tests)} tests passed.")
    return 0 if passed == len(tests) else 1


def scan_command(text): 
    lexer = make_lexer()
    try:
        tokens = lexer.tokenize(text)
    except LexerError as exc:
        print(f"LEXER ERROR: {exc}")
        return 1

    for token in tokens:
        print(f"{token.name:<12} {token.lexeme!r} [{token.start}:{token.end}]")
    return 0


def token_command(text): 
    lexer = make_lexer()
    token = lexer.accept_whole_token(text)
    if token is None:
        print("REJECT")
        return 1
    print(token)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Funny HW1: regex -> NFA -> DFA -> minimized DFA")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="build and serialize automata")

    sub.add_parser("test", help="run mandatory lexer tests")

    scan = sub.add_parser("scan", help="tokenize a Funny source string")
    scan.add_argument("text")

    tok = sub.add_parser("token", help="check whether the whole input is one token")
    tok.add_argument("text")

    args = parser.parse_args()

    if args.command == "build":
        build_command()
        return 0
    if args.command == "test":
        return test_command()
    if args.command == "scan":
        return scan_command(args.text)
    if args.command == "token":
        return token_command(args.text)

    return 2


if __name__ == "__main__":
    sys.exit(main())
