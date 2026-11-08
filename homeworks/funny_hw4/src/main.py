from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from automaton import build_automata, save_dfa
from lexer import Lexer, LexerError
from parser import parse as parse_tokens, offset_to_line_col, Parser
from ast_nodes import to_dict
from checker import check
from cfg import cfg_to_dot
from interp import IRRuntimeError, run_function
from ir import format_program, program_to_dict
from irtests import run_ir_tests
from optimize import PASSES, parse_opt_spec
from pipeline import compile_text, format_metrics, program_metrics
from regalloc import analyze, format_graph, graph_to_dot


ROOT = Path(__file__).resolve().parents[1]
TOKENS_FILE = ROOT / "tokens.json"
OUTPUT_DIR = ROOT / "output"
LEXER_TEST_FILE = ROOT / "tests" / "lexer_tests.json"
PARSER_TEST_FILE = ROOT / "tests" / "parser_tests.json"
SEMANTIC_TEST_FILE = ROOT / "tests" / "semantic_tests.json"
SAMPLES_DIR = ROOT / "samples"
AST_OUTPUT_DIR = OUTPUT_DIR / "ast"
IR_OUTPUT_DIR = OUTPUT_DIR / "ir"
IR_TEST_FILE = ROOT / "tests" / "ir_tests.json"


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
        print(f"LEXER ERROR: {exc}", file=sys.stderr)
        return 1

    module, errors = parse_tokens(tokens, text)

    for err in errors:
        line, col = offset_to_line_col(text, err.pos)
        print(f"PARSE ERROR [{line}:{col}]: {err.message}", file=sys.stderr)

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


KIND_RU = {"param": "параметр", "return": "возврат", "local": "локальная", "quantifier": "квантор"}


def check_command(text: str, as_json: bool):
    lexer = make_lexer()
    try:
        tokens = lexer.tokenize(text)
    except LexerError as exc:
        print(f"LEXER ERROR: {exc}", file=sys.stderr)
        return 1

    module, parse_errors = parse_tokens(tokens, text)
    if parse_errors:
        for err in parse_errors:
            line, col = offset_to_line_col(text, err.pos)
            print(f"PARSE ERROR [{line}:{col}]: {err.message}", file=sys.stderr)
        print("семантическая проверка пропущена: сначала исправьте синтаксические ошибки", file=sys.stderr)
        return 1

    errors = check(module, text)
    for err in errors:
        line, col = offset_to_line_col(text, err.pos)
        print(f"SEMANTIC ERROR [{line}:{col}]: {err.message}", file=sys.stderr)

    if as_json:
        print(json.dumps(to_dict(module, with_types=True), ensure_ascii=False, indent=2))
    else:
        print(f"functions: {len(module.functions)}, formulas: {len(module.formulas)}, semantic errors: {len(errors)}")
        for d in sorted(module.functions + module.formulas, key=lambda x: x.pos):
            kind = "function" if hasattr(d, "returns") else "formula "
            print(f"  {kind} {d.name}")
            for sym in d.symbols or []:
                how = "" if sym["declared"] else ", тип выведен"
                print(f"      {sym['name']}: {sym['type']}  ({KIND_RU[sym['kind']]}{how})")

    return 1 if errors else 0


def _analyze(lexer, text):
    tokens = lexer.tokenize(text)
    module, parse_errors = parse_tokens(tokens, text)
    if parse_errors:
        return module, parse_errors, None
    return module, [], check(module, text)


def semtest_command():
    lexer = make_lexer()
    tests = json.loads(SEMANTIC_TEST_FILE.read_text(encoding="utf-8"))["tests"]

    passed = 0
    for case in tests:
        name, text, kind = case["name"], case["input"], case["kind"]
        reasons = []

        try:
            module, syntax_errors, sem_errors = _analyze(lexer, text)
        except LexerError as exc:
            print(f"[FAIL] {name}")
            print(f"       лексер неожиданно упал: {exc}")
            continue

        if syntax_errors:
            reasons.append("неожиданные синтаксические ошибки: " + "; ".join(str(e) for e in syntax_errors))
        elif kind in ("ok", "annotated"):
            if sem_errors:
                for e in sem_errors:
                    line, col = offset_to_line_col(text, e.pos)
                    reasons.append(f"неожиданная ошибка [{line}:{col}]: {e.message}")
            if "expected_locals" in case:
                for fn_name, expected in case["expected_locals"].items():
                    fn = next((f for f in module.functions if f.name == fn_name), None)
                    actual = {u.name: u.ty for u in fn.uses} if fn else None
                    if actual != expected:
                        reasons.append(f"локальные {fn_name}: ожидалось {expected}, получено {actual}")
            if kind == "annotated":
                actual_ast = _strip_pos(to_dict(module, with_types=True))
                if actual_ast != _strip_pos(case["expected_ast"]):
                    reasons.append("аннотированный AST не совпал: actual=" + json.dumps(actual_ast, ensure_ascii=False))
        elif kind == "error":
            actual = []
            for e in sem_errors:
                line, col = offset_to_line_col(text, e.pos)
                actual.append((line, col, e.message))
            expected = case["expected_errors"]
            if len(actual) != len(expected):
                reasons.append(f"ожидалось ошибок: {len(expected)}, получено: {len(actual)}")
                for line, col, msg in actual:
                    reasons.append(f"  получено [{line}:{col}] {msg}")
            else:
                for (line, col, msg), exp in zip(actual, expected):
                    if (line, col) != (exp["line"], exp["col"]):
                        reasons.append(f"позиция: ожидалась {exp['line']}:{exp['col']}, получена {line}:{col} ({msg})")
                    if exp["contains"] not in msg:
                        reasons.append(f"сообщение [{line}:{col}] не содержит {exp['contains']!r}: {msg}")
        else:
            reasons.append(f"неизвестный kind: {kind}")

        ok = not reasons
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for r in reasons:
            print(f"       {r}")
        passed += int(ok)

    print(f"\n{passed}/{len(tests)} semantic tests passed.")
    return 0 if passed == len(tests) else 1


def _opt_title(enabled):
    return "оптимизации выключены" if not enabled else "оптимизации: " + ", ".join(p for p in PASSES if p in enabled)


def _coloring_dict(program):
    result = {}
    for fn in program.functions:
        graph, colors, count = analyze(fn)
        result[fn.name] = {
            "graph": {t: sorted(n) for t, n in sorted(graph.items())},
            "colors": dict(sorted(colors.items())),
            "color_count": count,
        }
    return result


def ir_command(text: str, spec: str, as_json: bool, show_graph: bool, dot_dir):
    try:
        enabled = parse_opt_spec(spec)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    before, after, errors = compile_text(text, make_lexer(), enabled)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print("IR не построен: сначала исправьте ошибки", file=sys.stderr)
        return 1

    if as_json:
        data = {
            "optimizations": [p for p in PASSES if p in enabled],
            "before": program_to_dict(before),
            "after": program_to_dict(after),
            "metrics": {"before": program_metrics(before), "after": program_metrics(after)},
            "coloring": {"before": _coloring_dict(before), "after": _coloring_dict(after)},
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print("===== IR до оптимизаций =====")
        print(format_program(before, show_cfg=True))
        print(f"===== IR после ({_opt_title(enabled)}) =====")
        print(format_program(after, show_cfg=True))
        print("===== Метрики =====")
        print("\n".join(format_metrics(before, after)))
        if show_graph:
            for title, program in (("до", before), ("после", after)):
                print(f"\n===== Граф конфликтов и раскраска ({title}) =====")
                for fn in program.functions:
                    graph, colors, _ = analyze(fn)
                    print("\n".join(format_graph(fn, graph, colors)))
                    print()

    if dot_dir:
        out = Path(dot_dir)
        out.mkdir(parents=True, exist_ok=True)
        _write_dot(out, before, after)
        print(f"DOT-файлы записаны в {out}", file=sys.stderr)
    return 0


def _write_dot(out: Path, before, after):
    for stage, program in (("before", before), ("after", after)):
        for fn in program.functions:
            (out / f"{fn.name}.cfg.{stage}.dot").write_text(cfg_to_dot(fn), encoding="utf-8")
            graph, colors, _ = analyze(fn)
            (out / f"{fn.name}.interference.{stage}.dot").write_text(graph_to_dot(fn, graph, colors), encoding="utf-8")


def run_command(text: str, func: str, args_text: str, spec: str):
    try:
        enabled = parse_opt_spec(spec)
        args = json.loads("[" + args_text + "]") if args_text.strip() else []
    except ValueError as exc:
        print(f"неверные аргументы: {exc}", file=sys.stderr)
        return 2

    before, after, errors = compile_text(text, make_lexer(), enabled)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    outcomes = []
    for title, program in (("до оптимизаций", before), (f"после ({_opt_title(enabled)})", after)):
        try:
            outcome = ("ok", run_function(program, func, args))
            print(f"{title}: {outcome[1]}")
        except IRRuntimeError as exc:
            outcome = ("error", str(exc))
            print(f"{title}: ошибка времени выполнения: {exc}")
        outcomes.append(outcome)
    same = outcomes[0] == outcomes[1]
    print("результаты совпадают" if same else "РЕЗУЛЬТАТЫ РАЗЛИЧАЮТСЯ")
    return 0 if same else 1


def irtest_command():
    lexer = make_lexer()
    tests = json.loads(IR_TEST_FILE.read_text(encoding="utf-8"))["tests"]
    passed = run_ir_tests(lexer, tests)
    return 0 if passed == len(tests) else 1


def export_ir(name: str, text: str, lexer):
    before, after, errors = compile_text(text, lexer, set(PASSES))
    if errors:
        return None
    out = IR_OUTPUT_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "before.ir").write_text(format_program(before, show_cfg=True), encoding="utf-8")
    (out / "after.ir").write_text(format_program(after, show_cfg=True), encoding="utf-8")
    data = {
        "optimizations": list(PASSES),
        "before": program_to_dict(before),
        "after": program_to_dict(after),
        "metrics": {"before": program_metrics(before), "after": program_metrics(after)},
        "coloring": {"before": _coloring_dict(before), "after": _coloring_dict(after)},
    }
    (out / "ir.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "metrics.txt").write_text("\n".join(format_metrics(before, after)) + "\n", encoding="utf-8")
    graph_lines = []
    for title, program in (("before", before), ("after", after)):
        graph_lines.append(f"##### {title}")
        for fn in program.functions:
            graph, colors, _ = analyze(fn)
            graph_lines.extend(format_graph(fn, graph, colors))
            graph_lines.append("")
    (out / "interference.txt").write_text("\n".join(graph_lines), encoding="utf-8")
    _write_dot(out, before, after)
    return out


def all_command():
    results = []
    for title, fn in (("lexer (HW1)", lextest_command), ("parser (HW2)", parsertest_command), ("semantic (HW3)", semtest_command), ("ir (HW4)", irtest_command)):
        print(f"===== {title} =====")
        results.append(fn())
        print()
    return 0 if all(r == 0 for r in results) else 1


def export_command():
    lexer = make_lexer()
    sources = sorted(SAMPLES_DIR.glob("*.funny"))
    if not sources:
        print(f"в {SAMPLES_DIR} нет файлов *.funny", file=sys.stderr)
        return 1

    AST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def dump(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for path in sources:
        text = path.read_text(encoding="utf-8")
        name = path.stem
        diagnostics = []
        written = []

        try:
            tokens = lexer.tokenize(text)
        except LexerError as exc:
            diagnostics.append(f"LEXER ERROR: {exc}")
            (AST_OUTPUT_DIR / f"{name}.diagnostics.txt").write_text("\n".join(diagnostics) + "\n", encoding="utf-8")
            print(f"{name}: ошибка лексера, AST не построен")
            continue

        module, parse_errors = parse_tokens(tokens, text)

        dump(AST_OUTPUT_DIR / f"{name}.ast.json", to_dict(module))
        written.append(f"{name}.ast.json")

        if parse_errors:
            for err in parse_errors:
                line, col = offset_to_line_col(text, err.pos)
                diagnostics.append(f"PARSE ERROR [{line}:{col}]: {err.message}")
            diagnostics.append("семантическая проверка пропущена: сначала исправьте синтаксические ошибки")
            sem_count = None
        else:
            sem_errors = check(module, text)
            for err in sem_errors:
                line, col = offset_to_line_col(text, err.pos)
                diagnostics.append(f"SEMANTIC ERROR [{line}:{col}]: {err.message}")
            dump(AST_OUTPUT_DIR / f"{name}.annotated.json", to_dict(module, with_types=True))
            written.append(f"{name}.annotated.json")
            sem_count = len(sem_errors)

        (AST_OUTPUT_DIR / f"{name}.diagnostics.txt").write_text(
            ("\n".join(diagnostics) if diagnostics else "no errors") + "\n", encoding="utf-8"
        )
        written.append(f"{name}.diagnostics.txt")

        status = "синтаксические ошибки" if sem_count is None else f"семантических ошибок: {sem_count}"
        print(f"{name}: {', '.join(written)} ({status})")

        if sem_count == 0:
            out_dir = export_ir(name, text, lexer)
            print(f"    IR и графы: {out_dir}")

    print(f"Output: {AST_OUTPUT_DIR}, {IR_OUTPUT_DIR}")
    return 0


def _read_source(args):
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if args.text is not None:
        return args.text
    print("нужно указать текст программы или --file PATH", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(description="Funny HW4: lexer (HW1) + parser (HW2) + semantics (HW3) + IR and optimizations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="build and serialize lexer automata (HW1)")
    sub.add_parser("lextest", help="run HW1 lexer regression tests")
    sub.add_parser("parsertest", help="run HW2 parser regression tests")
    sub.add_parser("semtest", help="run HW3 semantic regression tests")
    sub.add_parser("test", help="run HW4 IR / optimization tests")
    sub.add_parser("all", help="run lexer + parser + semantic + IR tests")
    sub.add_parser("export", help="write ASTs (output/ast/) and IR, CFG, graphs (output/ir/) for samples/*.funny")

    ast_p = sub.add_parser("ast", help="parse Funny source, print syntax tree (HW2)")
    ast_p.add_argument("text", nargs="?")
    ast_p.add_argument("--file", help="read source from file")
    ast_p.add_argument("--json", action="store_true", help="print AST as JSON")

    chk_p = sub.add_parser("check", help="semantic check: names, types, inference; annotated AST (HW3)")
    chk_p.add_argument("text", nargs="?")
    chk_p.add_argument("--file", help="read source from file")
    chk_p.add_argument("--json", action="store_true", help="print annotated AST as JSON")

    ir_p = sub.add_parser("ir", help="generate IR, build CFG, optimize, color temporaries (HW4)")
    ir_p.add_argument("text", nargs="?")
    ir_p.add_argument("--file", help="read source from file")
    ir_p.add_argument("--opt", default="all", help="all | none | comma list of: " + ", ".join(PASSES))
    ir_p.add_argument("--json", action="store_true", help="print IR before/after, metrics and coloring as JSON")
    ir_p.add_argument("--graph", action="store_true", help="print interference graph and coloring")
    ir_p.add_argument("--dot", metavar="DIR", help="write CFG and interference graphs as DOT files into DIR")

    run_p = sub.add_parser("run", help="execute a function before and after optimizations and compare results (HW4)")
    run_p.add_argument("text", nargs="?")
    run_p.add_argument("--file", help="read source from file")
    run_p.add_argument("--func", required=True, help="function name")
    run_p.add_argument("--args", default="", help="arguments as JSON list items, e.g. 3,[1,2,3] (write --args=-5,2 when the first one is negative)")
    run_p.add_argument("--opt", default="all", help="all | none | comma list of: " + ", ".join(PASSES))

    args = parser.parse_args()

    if args.command == "build":
        build_command()
        return 0
    if args.command == "lextest":
        return lextest_command()
    if args.command == "parsertest":
        return parsertest_command()
    if args.command == "semtest":
        return semtest_command()
    if args.command == "test":
        return irtest_command()
    if args.command == "all":
        return all_command()
    if args.command == "export":
        return export_command()
    if args.command == "ast":
        text = _read_source(args)
        return 2 if text is None else ast_command(text, args.json)
    if args.command == "check":
        text = _read_source(args)
        return 2 if text is None else check_command(text, args.json)
    if args.command == "ir":
        text = _read_source(args)
        return 2 if text is None else ir_command(text, args.opt, args.json, args.graph, args.dot)
    if args.command == "run":
        text = _read_source(args)
        return 2 if text is None else run_command(text, args.func, args.args, args.opt)

    return 2


if __name__ == "__main__":
    sys.exit(main())
