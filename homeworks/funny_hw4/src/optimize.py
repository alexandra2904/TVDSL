from __future__ import annotations

import copy

import ir
from ir import Instr, IRFunction, IRProgram, is_const
from cfg import liveness, live_after, reachable_labels

PASSES = ("constprop", "algebra", "dce")


def wrap32(x: int) -> int:
    return ((x + 2**31) % 2**32) - 2**31


def idiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return wrap32(q if (a >= 0) == (b >= 0) else -q)


def eval_bin(op: str, a: int, b: int):
    if op == "+":
        return wrap32(a + b)
    if op == "-":
        return wrap32(a - b)
    if op == "*":
        return wrap32(a * b)
    if op == "/":
        return None if b == 0 else idiv(a, b)
    return int({
        "==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b,
    }[op])


def const_prop(fn: IRFunction) -> bool:
    changed = False
    for block in fn.blocks:
        env = {}                              
        for idx, ins in enumerate(block.instrs):
            before = ins.copy()

            ins.args = [env.get(a, a) if isinstance(a, str) else a for a in ins.args]

            if ins.op == "bin" and all(is_const(a) for a in ins.args):
                value = eval_bin(ins.operator, ins.args[0], ins.args[1])
                if value is not None:
                    ins = ir.mov(ins.dsts[0], value)
            elif ins.op == "neg" and is_const(ins.args[0]):
                ins = ir.mov(ins.dsts[0], wrap32(-ins.args[0]))
            elif ins.op == "not" and is_const(ins.args[0]):
                ins = ir.mov(ins.dsts[0], 1 if ins.args[0] == 0 else 0)
            elif ins.op == "br" and is_const(ins.args[0]):
                ins = ir.jump(ins.targets[0] if ins.args[0] != 0 else ins.targets[1])

            for d in ins.dsts:               
                env.pop(d, None)
            if ins.op == "mov" and is_const(ins.args[0]):
                env[ins.dsts[0]] = ins.args[0]

            if ins != before:
                changed = True
            block.instrs[idx] = ins
    return changed


def _simplify_bin(ins: Instr):
    op = ins.operator
    a, b = ins.args
    d = ins.dsts[0]
    ac, bc = is_const(a), is_const(b)

    if op == "+":
        if bc and b == 0:
            return ir.mov(d, a)
        if ac and a == 0:
            return ir.mov(d, b)
    elif op == "-":
        if bc and b == 0:
            return ir.mov(d, a)
        if ac and a == 0:
            return ir.neg(d, b)
        if not ac and a == b:
            return ir.mov(d, 0)
    elif op == "*":
        if (bc and b == 0) or (ac and a == 0):
            return ir.mov(d, 0)
        if bc and b == 1:
            return ir.mov(d, a)
        if ac and a == 1:
            return ir.mov(d, b)
    elif op == "/":
        if bc and b == 1:
            return ir.mov(d, a)
    elif op in ir.CMP_OPS:
        if not ac and a == b:                 
            return ir.mov(d, 1 if op in ("==", "<=", ">=") else 0)
    return None


def algebra(fn: IRFunction) -> bool:
    changed = False
    for block in fn.blocks:
        new = []
        for ins in block.instrs:
            if ins.op == "bin":
                simplified = _simplify_bin(ins)
                if simplified is not None:
                    ins = simplified
                    changed = True
            if ins.op == "mov" and ins.args[0] == ins.dsts[0]:     
                changed = True
                continue
            new.append(ins)
        block.instrs = new
    return changed


def is_pure(ins: Instr) -> bool:
    if ins.op in ("mov", "copy", "len", "neg", "not"):
        return True
    if ins.op == "bin":
        if ins.operator == "/":
            return is_const(ins.args[1]) and ins.args[1] != 0
        return True
    return False


def dce(fn: IRFunction) -> bool:
    changed = False

    reachable = reachable_labels(fn)
    if len(reachable) != len(fn.blocks):
        fn.blocks = [b for b in fn.blocks if b.label in reachable]
        changed = True

    while True:
        _, live_out = liveness(fn)
        removed = False
        for block in fn.blocks:
            after = live_after(block, live_out[block.label])
            kept = []
            for ins, live in zip(block.instrs, after):
                if is_pure(ins) and ins.dsts and all(d not in live for d in ins.dsts):
                    removed = True
                    continue
                kept.append(ins)
            block.instrs = kept
        if not removed:
            break
        changed = True
    return changed



_IMPL = {"constprop": const_prop, "algebra": algebra, "dce": dce}


def optimize_function(fn: IRFunction, enabled: set, max_rounds: int = 20) -> IRFunction:
    for _ in range(max_rounds):
        changed = False
        for name in PASSES:
            if name in enabled:
                changed |= _IMPL[name](fn)
        if not changed:
            break
    return fn


def optimize_program(program: IRProgram, enabled: set) -> IRProgram:
    result = copy.deepcopy(program)
    for fn in result.functions:
        optimize_function(fn, enabled)
    return result


def parse_opt_spec(spec: str) -> set:
    spec = spec.strip().lower()
    if spec == "all":
        return set(PASSES)
    if spec in ("none", ""):
        return set()
    names = {s.strip() for s in spec.split(",")}
    unknown = names - set(PASSES)
    if unknown:
        raise ValueError(f"неизвестные оптимизации: {', '.join(sorted(unknown))}; допустимо: all, none, {', '.join(PASSES)}")
    return names
