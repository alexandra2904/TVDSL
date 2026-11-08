from __future__ import annotations

from dataclasses import dataclass, field

INT = "int"
INT_ARR = "int[]"

ARITH_OPS = ("+", "-", "*", "/")
CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")
BIN_OPS = ARITH_OPS + CMP_OPS
TERMINATORS = ("jump", "br", "ret")


def is_const(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def is_temp(name) -> bool:
    return isinstance(name, str) and name.startswith("%")


@dataclass
class Instr:
    op: str
    dsts: list = field(default_factory=list)       
    args: list = field(default_factory=list)       
    operator: str | None = None                   
    callee: str | None = None                      
    targets: list = field(default_factory=list)    

    def uses(self) -> list:
        return [a for a in self.args if isinstance(a, str)]

    def defs(self) -> list:
        return list(self.dsts)

    def copy(self) -> "Instr":
        return Instr(self.op, list(self.dsts), list(self.args), self.operator, self.callee, list(self.targets))


def mov(dst, a):
    return Instr("mov", [dst], [a])


def copy_arr(dst, a):
    return Instr("copy", [dst], [a])


def binop(dst, operator, a, b):
    return Instr("bin", [dst], [a, b], operator=operator)


def neg(dst, a):
    return Instr("neg", [dst], [a])


def not_(dst, a):
    return Instr("not", [dst], [a])


def aload(dst, arr, i):
    return Instr("aload", [dst], [arr, i])


def astore(arr, i, v):
    return Instr("astore", [arr], [arr, i, v])


def length(dst, arr):
    return Instr("len", [dst], [arr])


def call(dsts, callee, args):
    return Instr("call", list(dsts), list(args), callee=callee)


def jump(label):
    return Instr("jump", targets=[label])


def br(cond, true_label, false_label):
    return Instr("br", args=[cond], targets=[true_label, false_label])


def ret(args):
    return Instr("ret", args=list(args))


def label(name):
    return Instr("label", targets=[name])


def format_instr(i: Instr) -> str:
    op = i.op
    if op == "label":
        return f"{i.targets[0]}:"
    if op == "mov":
        return f"{i.dsts[0]} = {i.args[0]}"
    if op == "copy":
        return f"{i.dsts[0]} = copy {i.args[0]}"
    if op == "bin":
        return f"{i.dsts[0]} = {i.args[0]} {i.operator} {i.args[1]}"
    if op == "neg":
        return f"{i.dsts[0]} = -{i.args[0]}"
    if op == "not":
        return f"{i.dsts[0]} = not {i.args[0]}"
    if op == "aload":
        return f"{i.dsts[0]} = {i.args[0]}[{i.args[1]}]"
    if op == "astore":
        return f"{i.args[0]}[{i.args[1]}] = {i.args[2]}"
    if op == "len":
        return f"{i.dsts[0]} = length {i.args[0]}"
    if op == "call":
        return f"{', '.join(i.dsts)} = call {i.callee}({', '.join(str(a) for a in i.args)})"
    if op == "jump":
        return f"jump {i.targets[0]}"
    if op == "br":
        return f"br {i.args[0]}, {i.targets[0]}, {i.targets[1]}"
    if op == "ret":
        return "ret " + ", ".join(str(a) for a in i.args)
    raise ValueError(f"неизвестная операция IR: {op}")


def instr_to_dict(i: Instr) -> dict:
    d = {"op": i.op}
    if i.dsts:
        d["dsts"] = list(i.dsts)
    if i.args:
        d["args"] = list(i.args)
    if i.operator is not None:
        d["operator"] = i.operator
    if i.callee is not None:
        d["callee"] = i.callee
    if i.targets:
        d["targets"] = list(i.targets)
    return d


@dataclass
class Block:
    label: str
    instrs: list = field(default_factory=list)

    def terminator(self):
        return self.instrs[-1] if self.instrs and self.instrs[-1].op in TERMINATORS else None

    def succs(self) -> list:
        t = self.terminator()
        if t is None or t.op == "ret":
            return []
        out = []
        for target in t.targets:
            if target not in out:
                out.append(target)
        return out


@dataclass
class IRFunction:
    name: str
    params: list            
    returns: list           
    locals: list           
    temps: dict = field(default_factory=dict)      
    code: list = field(default_factory=list)       
    blocks: list = field(default_factory=list)

    def var_types(self) -> dict:
        types = {}
        for name, ty in self.params + self.returns + self.locals:
            types[name] = ty
        types.update(self.temps)
        return types

    def instructions(self):
        for block in self.blocks:
            for ins in block.instrs:
                yield ins

    def used_temps(self) -> list:
        seen = []
        for ins in self.instructions():
            for name in list(ins.dsts) + ins.uses():
                if is_temp(name) and name not in seen:
                    seen.append(name)
        return sorted(seen, key=lambda t: int(t[2:]))

    def instr_count(self) -> int:
        return sum(len(b.instrs) for b in self.blocks)


@dataclass
class IRProgram:
    functions: list = field(default_factory=list)

    def get(self, name: str):
        for fn in self.functions:
            if fn.name == name:
                return fn
        return None


def _decls(items) -> str:
    return ", ".join(f"{n}: {t}" for n, t in items)


def format_function(fn: IRFunction, show_cfg: bool = False) -> list:
    lines = [f"function {fn.name}({_decls(fn.params)}) returns ({_decls(fn.returns)})"]
    if fn.locals:
        lines.append(f"  locals: {_decls(fn.locals)}")
    used = fn.used_temps()
    if used:
        lines.append("  temps: " + ", ".join(f"{t}: {fn.temps[t]}" for t in used))
    for block in fn.blocks:
        header = f"{block.label}:"
        if show_cfg:
            succs = block.succs()
            header += "    ; -> " + (", ".join(succs) if succs else "(выход)")
        lines.append(header)
        for ins in block.instrs:
            lines.append("    " + format_instr(ins))
    return lines


def format_program(program: IRProgram, show_cfg: bool = False) -> str:
    chunks = ["\n".join(format_function(fn, show_cfg)) for fn in program.functions]
    return "\n\n".join(chunks) + "\n"


def function_to_dict(fn: IRFunction) -> dict:
    used = fn.used_temps()
    return {
        "name": fn.name,
        "params": [{"name": n, "type": t} for n, t in fn.params],
        "returns": [{"name": n, "type": t} for n, t in fn.returns],
        "locals": [{"name": n, "type": t} for n, t in fn.locals],
        "temps": [{"name": t, "type": fn.temps[t]} for t in used],
        "blocks": [
            {
                "label": b.label,
                "instrs": [instr_to_dict(i) for i in b.instrs],
                "succs": b.succs(),
            }
            for b in fn.blocks
        ],
    }


def program_to_dict(program: IRProgram) -> dict:
    return {"functions": [function_to_dict(fn) for fn in program.functions]}
