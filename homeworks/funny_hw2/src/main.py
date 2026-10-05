from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from automaton import build_automata, save_dfa
from lexer import Lexer, LexerError
from parser import parse as parse_tokens, offset_to_line_col, Parser
from ast_nodes import to_dict


ROOT = Path(__file__).resolve().parents[1]
TOKENS_FILE = ROOT / "tokens.json"
OUTPUT_DIR = ROOT / "output"
LEXER_TEST_FILE = ROOT / "tests" / "lexer_tests.json"
PARSER_TEST_FILE = ROOT / "tests" / "parser_tests.json"


def load_specs():
    data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    return data["tokens"]


def make_lexer():
    specs = load_specs()
    _, _, minimized = build_automata(specs)
    return Lexer(minimized, specs)


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
    (OUTPUT_DIR / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print("Build completed.")
    print(f"NFA states: {stats['nfa_states']}")
    print(f"DFA states before minimization: {stats['dfa_states_before_minimization']}")
    print(f"DFA states after minimization:  {stats['dfa_states_after_minimization']}")
    print(f"Output: {OUTPUT_DIR}")


def lextest_command():
    lexer = make_lexer()
    tests = json.loads(LEXER_TEST_FILE.read_text(encoding="utf-8"))["tests"]

    passed = 0
    for case in tests:
        kind = case["kind"]
        text = case["input"]
        try:
            if kind == "token":
                actual = lexer.accept_whole_token(text)
                ok = actual == case.get("expected_token")
            elif kind == "source":
                actual_tokens = [t.as_dict() for t in lexer.tokenize(text)]
                ok = [{"token": x["token"], "lexeme": x["lexeme"]} for x in actual_tokens] == case.get("expected_tokens", [])
            elif kind == "error":
                try:
                    lexer.tokenize(text)
                    ok = False
                except LexerError:
                    ok = True
            else:
                raise ValueError(f"unknown test kind: {kind}")
        except Exception:
            ok = False

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['name']}")
        passed += int(ok)

    print(f"\n{passed}/{len(tests)} lexer tests passed.")
    return 0 if passed == len(tests) else 1


def ast_command(text: str, as_json: bool):
    lexer = make_lexer()
    try:
        tokens = lexer.tokenize(text)
    except LexerError as exc:
        print(f"LEXER ERROR: {exc}")
        return 1

    module, errors = parse_tokens(tokens, text)

    for err in errors:
        line, col = offset_to_line_col(text, err.pos)
        print(f"PARSE ERROR [{line}:{col}]: {err.message}")

    if as_json:
        print(json.dumps(to_dict(module), ensure_ascii=False, indent=2))
    else:
        print(f"functions: {len(module.functions)}, formulas: {len(module.formulas)}")
        for fn in module.functions:
            print(f"  function {fn.name}({', '.join(p.name + ':' + p.type for p in fn.params)})")
        for fm in module.formulas:
            print(f"  formula  {fm.name}({', '.join(p.name + ':' + p.type for p in fm.params)})")

    return 1 if errors else 0


def _tokens_for(lexer, text):
    return lexer.tokenize(text)


def _ast_shape_matches(node, expected) -> bool:
    actual = to_dict(node)
    return _strip_pos(actual) == _strip_pos(expected)


def _strip_pos(value):
    if isinstance(value, dict):
        return {k: _strip_pos(v) for k, v in value.items() if k != "pos"}
    if isinstance(value, list):
        return [_strip_pos(v) for v in value]
    return value


def parsertest_command():
    lexer = make_lexer()
    tests = json.loads(PARSER_TEST_FILE.read_text(encoding="utf-8"))["tests"]

    passed = 0
    for case in tests:
        name = case["name"]
        text = case["input"]
        kind = case["kind"]  

        try:
            tokens = _tokens_for(lexer, text)
        except LexerError as exc:
            if kind == "error":
                print(f"[PASS] {name}")
                passed += 1
            else:
                print(f"[FAIL] {name}")
                print(f"       лексер неожиданно упал: {exc}")
            continue

        if kind == "expr":
            p = Parser(tokens, text)
            try:
                node = p._parse_expr()
                leftover = p._current() is None
            except Exception:
                node, leftover = None, False
            ok = leftover and node is not None and _ast_shape_matches(node, case["expected_ast"])
            if not ok:
                print(f"[FAIL] {name}")
                if node is not None:
                    print(f"       actual:   {json.dumps(_strip_pos(to_dict(node)), ensure_ascii=False)}")
                print(f"       expected: {json.dumps(case['expected_ast'], ensure_ascii=False)}")
            else:
                print(f"[PASS] {name}")
            passed += int(ok)
            continue

        module, errors = parse_tokens(tokens, text)

        if kind == "error":
            ok = len(errors) > 0
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            if not ok:
                print("       ожидалась синтаксическая ошибка, но разбор прошёл чисто")
            passed += int(ok)
            continue

        if kind == "module_errors":
            ok = True
            reasons = []

            if "expected_error_count" in case and len(errors) != case["expected_error_count"]:
                ok = False
                reasons.append(f"ожидалось ошибок: {case['expected_error_count']}, получено: {len(errors)}")

            texts = [str(e) for e in errors]
            for needle in case.get("expected_error_contains", []):
                if not any(needle in t for t in texts):
                    ok = False
                    reasons.append(f"ни одна ошибка не содержит {needle!r}; ошибки: {texts}")

            if "expected_ast" in case and not _ast_shape_matches(module, case["expected_ast"]):
                ok = False
                reasons.append(
                    "AST не совпал: actual="
                    + json.dumps(_strip_pos(to_dict(module)), ensure_ascii=False)
                )

            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            for r in reasons:
                print(f"       {r}")
            passed += int(ok)
            continue

        ok = not errors and _ast_shape_matches(module, case["expected_ast"])
        if not ok:
            print(f"[FAIL] {name}")
            if errors:
                for err in errors:
                    print(f"       error: {err}")
            else:
                print(f"       actual:   {json.dumps(_strip_pos(to_dict(module)), ensure_ascii=False)}")
                print(f"       expected: {json.dumps(case['expected_ast'], ensure_ascii=False)}")
        else:
            print(f"[PASS] {name}")
        passed += int(ok)

    print(f"\n{passed}/{len(tests)} parser tests passed.")
    return 0 if passed == len(tests) else 1


def main():
    parser = argparse.ArgumentParser(description="Funny HW2: lexer (HW1) + LL(1) parser -> AST")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="build and serialize lexer automata (HW1)")
    sub.add_parser("lextest", help="run HW1 lexer regression tests")
    sub.add_parser("test", help="run HW2 parser tests")

    ast_p = sub.add_parser("ast", help="parse Funny source, print AST")
    ast_p.add_argument("text")
    ast_p.add_argument("--json", action="store_true", help="print AST as JSON")

    args = parser.parse_args()

    if args.command == "build":
        build_command()
        return 0
    if args.command == "lextest":
        return lextest_command()
    if args.command == "test":
        return parsertest_command()
    if args.command == "ast":
        return ast_command(args.text, args.json)

    return 2


if __name__ == "__main__":
    sys.exit(main())
