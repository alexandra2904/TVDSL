from __future__ import annotations

from lexer import LexerError
from parser import parse as parse_tokens, offset_to_line_col
from checker import check
from irgen import generate
from cfg import build_blocks
from optimize import optimize_program
from regalloc import analyze
from ir import IRProgram


def front_end(text: str, lexer):
    try:
        tokens = lexer.tokenize(text)
    except LexerError as exc:
        return None, [f"LEXER ERROR: {exc}"]

    module, parse_errors = parse_tokens(tokens, text)
    if parse_errors:
        out = []
        for e in parse_errors:
            line, col = offset_to_line_col(text, e.pos)
            out.append(f"PARSE ERROR [{line}:{col}]: {e.message}")
        return None, out

    sem_errors = check(module, text)
    if sem_errors:
        out = []
        for e in sem_errors:
            line, col = offset_to_line_col(text, e.pos)
            out.append(f"SEMANTIC ERROR [{line}:{col}]: {e.message}")
        return None, out
    return module, []


def build_ir(module) -> IRProgram:
    program = generate(module)
    for fn in program.functions:
        build_blocks(fn)
    return program


def compile_text(text: str, lexer, enabled: set):
    module, errors = front_end(text, lexer)
    if errors:
        return None, None, errors
    before = build_ir(module)
    after = optimize_program(before, enabled)
    return before, after, []


def function_metrics(fn) -> dict:
    graph, colors, n_colors = analyze(fn)
    return {
        "blocks": len(fn.blocks),
        "instrs": fn.instr_count(),
        "temps": len(fn.used_temps()),
        "colors": n_colors,
    }


def program_metrics(program: IRProgram) -> dict:
    return {fn.name: function_metrics(fn) for fn in program.functions}


def format_metrics(before: IRProgram, after: IRProgram) -> list:
    mb, ma = program_metrics(before), program_metrics(after)
    head = f"{'функция':<14}{'блоков':>12}{'инструкций':>14}{'временных':>14}{'цветов':>12}"
    sub = f"{'':<14}{'до→после':>12}{'до→после':>14}{'до→после':>14}{'до→после':>12}"
    lines = [head, sub]
    total = {k: [0, 0] for k in ("blocks", "instrs", "temps")}
    for name in mb:
        row = f"{name:<14}"
        for key, width in (("blocks", 12), ("instrs", 14), ("temps", 14), ("colors", 12)):
            cell = f"{mb[name][key]} → {ma[name][key]}"
            row += f"{cell:>{width}}"
            if key in total:
                total[key][0] += mb[name][key]
                total[key][1] += ma[name][key]
        lines.append(row)
    row = f"{'всего':<14}"
    for key, width in (("blocks", 12), ("instrs", 14), ("temps", 14)):
        row += f"{str(total[key][0]) + ' → ' + str(total[key][1]):>{width}}"
    row += f"{'-':>12}"
    lines.append(row)
    return lines
