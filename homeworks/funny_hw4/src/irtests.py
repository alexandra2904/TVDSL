from __future__ import annotations

import random

from cfg import edges
from interp import IRRuntimeError, run_function
from ir import format_function
from optimize import parse_opt_spec
from pipeline import compile_text, function_metrics
from regalloc import analyze, check_coloring
from validate import validate_program

MODES = ["none", "constprop", "algebra", "dce", "constprop,dce", "all"]



def _compile(text, lexer, spec):
    before, after, errors = compile_text(text, lexer, parse_opt_spec(spec))
    if errors:
        raise AssertionError("программа не прошла проверку: " + "; ".join(errors))
    return before, after


def invariants(before, after) -> list:
    problems = []
    for label, program in (("до", before), ("после", after)):
        for p in validate_program(program):
            problems.append(f"IR {label}: {p}")
        for fn in program.functions:
            graph, colors, _ = analyze(fn)
            for p in check_coloring(graph, colors, fn.temps):
                problems.append(f"раскраска {label} ({fn.name}): {p}")
    for fb, fa in zip(before.functions, after.functions):
        if fa.instr_count() > fb.instr_count():
            problems.append(f"{fb.name}: оптимизация увеличила число инструкций ({fb.instr_count()} -> {fa.instr_count()})")
    return problems


def _execute(program, func, args):
    try:
        return ("ok", run_function(program, func, args))
    except IRRuntimeError as exc:
        return ("error", str(exc))


def _fmt(result):
    return f"{result[0]}: {result[1]}"



def _t_run(lexer, case):
    reasons = []
    modes = case.get("modes", MODES)
    for spec in modes:
        before, after = _compile(case["input"], lexer, spec)
        reasons += [f"[{spec}] {p}" for p in invariants(before, after)]
        for c in case["cases"]:
            for stage, program in (("до", before), ("после", after)):
                got = _execute(program, case["function"], c["args"])
                if "expect" in c:
                    ok = got == ("ok", c["expect"])
                else:
                    ok = got[0] == "error" and c["error"] in got[1]
                if not ok:
                    want = c.get("expect", c.get("error"))
                    reasons.append(f"[{spec}, {stage}] args={c['args']}: получено {_fmt(got)}, ожидалось {want}")
    return reasons


def _t_ir(lexer, case):
    before, after = _compile(case["input"], lexer, case.get("opt", "all"))
    reasons = [f"{p}" for p in invariants(before, after)]
    for stage, program in (("before", before), ("after", after)):
        fn = program.get(case["function"])
        got = format_function(fn, show_cfg=False)
        want = case[stage]
        if got != want:
            reasons.append(f"IR {stage} не совпал:\n" + "\n".join("         " + l for l in got))
    return reasons


def _t_cfg(lexer, case):
    before, after = _compile(case["input"], lexer, "none")
    reasons = invariants(before, after)
    fn = before.get(case["function"])
    got = {b.label: b.succs() for b in fn.blocks}
    if got != case["blocks"]:
        reasons.append(f"CFG: получено {got}, ожидалось {case['blocks']}")
    if len(edges(fn)) != sum(len(v) for v in case["blocks"].values()):
        reasons.append("число рёбер не совпало")
    return reasons


def _t_metrics(lexer, case):
    before, after = _compile(case["input"], lexer, case.get("opt", "all"))
    reasons = invariants(before, after)
    fn_name = case["function"]
    got = {"before": function_metrics(before.get(fn_name)), "after": function_metrics(after.get(fn_name))}
    for stage in ("before", "after"):
        if got[stage] != case[stage]:
            reasons.append(f"метрики {stage}: получено {got[stage]}, ожидалось {case[stage]}")
    return reasons


def _t_flags(lexer, case):
    reasons = []
    got = {}
    for spec in case["instrs"]:
        before, after = _compile(case["input"], lexer, spec)
        reasons += [f"[{spec}] {p}" for p in invariants(before, after)]
        got[spec] = after.get(case["function"]).instr_count()
    if got != case["instrs"]:
        reasons.append(f"число инструкций по режимам: получено {got}, ожидалось {case['instrs']}")
    return reasons



def _int_expr(rng, depth, names):
    if depth == 0 or rng.random() < 0.25:
        if rng.random() < 0.5:
            return rng.choice(["0", "1", "2", "3", "(-1)", "(-3)", "7"])
        return rng.choice(names)
    kind = rng.random()
    if kind < 0.1:
        return f"(-{_int_expr(rng, depth - 1, names)})"
    op = rng.choice(["+", "-", "*", "+", "-", "*", "/"])
    return f"({_int_expr(rng, depth - 1, names)} {op} {_int_expr(rng, depth - 1, names)})"


def _bool_expr(rng, depth, names):
    if depth == 0 or rng.random() < 0.4:
        op = rng.choice(["==", "!=", "<", "<=", ">", ">="])
        return f"({_int_expr(rng, 2, names)} {op} {_int_expr(rng, 2, names)})"
    kind = rng.choice(["not", "and", "or", "->"])
    if kind == "not":
        return f"(not {_bool_expr(rng, depth - 1, names)})"
    return f"({_bool_expr(rng, depth - 1, names)} {kind} {_bool_expr(rng, depth - 1, names)})"


def random_program(rng) -> str:
    names = ["x", "y", "z"]
    lines = ["function f(x: int, y: int, z: int) returns r: int uses a, b, i {"]
    lines.append(f"    a = {_int_expr(rng, 3, names)};")
    lines.append(f"    b = {_int_expr(rng, 3, names + ['a'])};")
    lines.append(f"    a = {_int_expr(rng, 2, names + ['b'])};")      
    lines.append(f"    b = b + {_int_expr(rng, 2, names + ['a'])};")
    names2 = names + ["a", "b"]
    lines.append(f"    if {_bool_expr(rng, 2, names2)} {{ r = {_int_expr(rng, 3, names2)}; }} else {{ r = {_int_expr(rng, 3, names2)}; }}")
    lines.append("    i = 0;")
    lines.append("    while (i < 3) {")
    lines.append(f"        r = r + {_int_expr(rng, 2, names2 + ['i'])};")
    lines.append(f"        if {_bool_expr(rng, 1, names2 + ['i', 'r'])} {{ b = b + 1; }}")
    lines.append("        i = i + 1;")
    lines.append("    }")
    lines.append(f"    r = r + {_int_expr(rng, 2, names2 + ['r'])};")
    lines.append("}")
    return "\n".join(lines)


def _t_fuzz(lexer, case):
    rng = random.Random(case["seed"])
    grid = [[x, y, z] for x in (-3, 0, 5) for y in (-1, 0, 2) for z in (0, 1, 4)]
    reasons = []
    checked = 0
    for n in range(case["count"]):
        text = random_program(rng)
        base = None
        for spec in MODES:
            before, after = _compile(text, lexer, spec)
            problems = invariants(before, after)
            if problems:
                reasons.append(f"программа #{n} [{spec}]: {problems[0]}\n{text}")
                break
            if base is None:
                base = [_execute(before, "f", args) for args in grid]
            for args in grid:
                want = base[grid.index(args)]
                got = _execute(after, "f", args)
                checked += 1
                if got != want:
                    reasons.append(f"программа #{n} [{spec}] args={args}: до {_fmt(want)}, после {_fmt(got)}\n{text}")
                    break
            if reasons:
                break
        if reasons:
            break
    case["_checked"] = checked
    return reasons


_KINDS = {"run": _t_run, "ir": _t_ir, "cfg": _t_cfg, "metrics": _t_metrics, "flags": _t_flags, "fuzz": _t_fuzz}


def run_ir_tests(lexer, tests: list) -> int:
    passed = 0
    for case in tests:
        try:
            reasons = _KINDS[case["kind"]](lexer, case)
        except Exception as exc:       
            reasons = [f"исключение {type(exc).__name__}: {exc}"]
        ok = not reasons
        extra = f" ({case['_checked']} сравнений)" if case["kind"] == "fuzz" and ok else ""
        print(f"[{'PASS' if ok else 'FAIL'}] {case['name']}{extra}")
        for r in reasons:
            print(f"       {r}")
        passed += int(ok)
    print(f"\n{passed}/{len(tests)} IR tests passed.")
    return passed
