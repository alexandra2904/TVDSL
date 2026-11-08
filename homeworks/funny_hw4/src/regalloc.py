from __future__ import annotations

from ir import IRFunction, is_temp
from cfg import liveness, live_after

PALETTE = ["lightblue", "lightgreen", "khaki", "lightpink", "lightsalmon",
           "plum", "lightcyan", "wheat", "thistle", "palegreen"]


def interference_graph(fn: IRFunction) -> dict:
    graph = {t: set() for t in fn.used_temps()}
    _, live_out = liveness(fn)
    for block in fn.blocks:
        after = live_after(block, live_out[block.label])
        for ins, live in zip(block.instrs, after):
            defined = [d for d in ins.defs() if is_temp(d)]
            for d in defined:
                for v in live:
                    if is_temp(v) and v != d:
                        graph[d].add(v)
                        graph[v].add(d)
                for other in defined:
                    if other != d:
                        graph[d].add(other)
                        graph[other].add(d)
    return graph


def greedy_coloring(graph: dict, types: dict) -> dict:
    colors = {}
    color_type = {}                      
    order = sorted(graph, key=lambda t: (-len(graph[t]), t))
    for t in order:
        taken = {colors[n] for n in graph[t] if n in colors}
        c = 0
        while c in taken or color_type.get(c, types[t]) != types[t]:
            c += 1
        colors[t] = c
        color_type[c] = types[t]
    return colors


def check_coloring(graph: dict, colors: dict, types: dict) -> list:
    problems = []
    for t, neighbours in graph.items():
        if t not in colors:
            problems.append(f"{t}: нет цвета")
            continue
        for n in neighbours:
            if colors.get(n) == colors[t]:
                problems.append(f"{t} и {n} конфликтуют, но окрашены одинаково ({colors[t]})")
    by_color = {}
    for t, c in colors.items():
        by_color.setdefault(c, set()).add(types[t])
    for c, kinds in by_color.items():
        if len(kinds) > 1:
            problems.append(f"цвет {c} делят временные разных типов: {sorted(kinds)}")
    return problems


def color_count(colors: dict) -> int:
    return len(set(colors.values()))


def analyze(fn: IRFunction):
    graph = interference_graph(fn)
    colors = greedy_coloring(graph, fn.temps)
    return graph, colors, color_count(colors)


def format_graph(fn: IRFunction, graph: dict, colors: dict) -> list:
    lines = [f"interference graph of {fn.name}:"]
    if not graph:
        lines.append("  (временных нет)")
    for t in sorted(graph, key=lambda x: int(x[2:])):
        neighbours = ", ".join(sorted(graph[t], key=lambda x: int(x[2:]))) or "-"
        lines.append(f"  {t} ({fn.temps[t]}) -- {neighbours}")
    lines.append("coloring (greedy, по убыванию степени):")
    for t in sorted(colors, key=lambda x: int(x[2:])):
        lines.append(f"  {t} -> color {colors[t]}")
    lines.append(f"colors: {color_count(colors)}")
    return lines


def graph_to_dot(fn: IRFunction, graph: dict, colors: dict) -> str:
    lines = [f'graph "{fn.name}_interference" {{', "  node [style=filled, fontname=Courier];"]
    for t in sorted(graph, key=lambda x: int(x[2:])):
        color = PALETTE[colors[t] % len(PALETTE)]
        lines.append(f'  "{t}" [label="{t}\\ncolor {colors[t]}", fillcolor={color}];')
    done = set()
    for t in sorted(graph, key=lambda x: int(x[2:])):
        for n in sorted(graph[t], key=lambda x: int(x[2:])):
            edge = tuple(sorted((t, n)))
            if edge not in done:
                done.add(edge)
                lines.append(f'  "{edge[0]}" -- "{edge[1]}";')
    lines.append("}")
    return "\n".join(lines) + "\n"
