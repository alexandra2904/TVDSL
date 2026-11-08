from __future__ import annotations

from ir import Block, IRFunction, TERMINATORS, jump


def build_blocks(fn: IRFunction) -> IRFunction:
    blocks = []
    cur = None
    anonymous = 0

    for ins in fn.code:
        if ins.op == "label":
            name = ins.targets[0]
            if cur is not None and not (cur.instrs and cur.instrs[-1].op in TERMINATORS):
                cur.instrs.append(jump(name))
            cur = Block(name)
            blocks.append(cur)
            continue
        if cur is None:                       
            anonymous += 1
            cur = Block(f"B{anonymous}")
            blocks.append(cur)
        cur.instrs.append(ins)
        if ins.op in TERMINATORS:
            cur = None

    if cur is not None:
        raise ValueError(f"функция {fn.name}: последний блок не завершён терминатором")
    fn.blocks = blocks
    return fn


def block_map(fn: IRFunction) -> dict:
    return {b.label: b for b in fn.blocks}


def edges(fn: IRFunction) -> list:
    return [(b.label, s) for b in fn.blocks for s in b.succs()]


def predecessors(fn: IRFunction) -> dict:
    preds = {b.label: [] for b in fn.blocks}
    for src, dst in edges(fn):
        preds[dst].append(src)
    return preds


def reachable_labels(fn: IRFunction) -> set:
    if not fn.blocks:
        return set()
    by_label = block_map(fn)
    seen = set()
    stack = [fn.blocks[0].label]
    while stack:
        label = stack.pop()
        if label in seen:
            continue
        seen.add(label)
        stack.extend(by_label[label].succs())
    return seen


def block_use_def(block: Block):
    use, defs = set(), set()
    for ins in block.instrs:
        for u in ins.uses():
            if u not in defs:
                use.add(u)
        defs.update(ins.defs())
    return use, defs


def liveness(fn: IRFunction):
    use_def = {b.label: block_use_def(b) for b in fn.blocks}
    live_in = {b.label: set() for b in fn.blocks}
    live_out = {b.label: set() for b in fn.blocks}
    changed = True
    while changed:
        changed = False
        for block in reversed(fn.blocks):
            out = set()
            for s in block.succs():
                out |= live_in[s]
            use, defs = use_def[block.label]
            new_in = use | (out - defs)
            if out != live_out[block.label] or new_in != live_in[block.label]:
                live_out[block.label] = out
                live_in[block.label] = new_in
                changed = True
    return live_in, live_out


def live_after(block: Block, live_out_of_block: set) -> list:
    live = set(live_out_of_block)
    result = [None] * len(block.instrs)
    for i in range(len(block.instrs) - 1, -1, -1):
        ins = block.instrs[i]
        result[i] = set(live)
        live = (live - set(ins.defs())) | set(ins.uses())
    return result


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("<", "\\<").replace(">", "\\>").replace("{", "\\{").replace("}", "\\}").replace("|", "\\|")


def cfg_to_dot(fn: IRFunction) -> str:
    from ir import format_instr

    lines = [f'digraph "{fn.name}" {{', "  node [shape=record, fontname=Courier];"]
    for b in fn.blocks:
        body = "\\l".join(_dot_escape(format_instr(i)) for i in b.instrs) + "\\l"
        lines.append(f'  "{b.label}" [label="{{{b.label}:|{body}}}"];')
    for b in fn.blocks:
        term = b.terminator()
        if term is not None and term.op == "br":
            lines.append(f'  "{b.label}" -> "{term.targets[0]}" [label="true"];')
            lines.append(f'  "{b.label}" -> "{term.targets[1]}" [label="false"];')
        else:
            for s in b.succs():
                lines.append(f'  "{b.label}" -> "{s}";')
    lines.append("}")
    return "\n".join(lines) + "\n"
