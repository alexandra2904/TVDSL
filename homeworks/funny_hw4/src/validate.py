from __future__ import annotations

from ir import IRFunction, IRProgram, TERMINATORS, BIN_OPS, INT, INT_ARR, is_const, format_instr


def validate_function(fn: IRFunction, program: IRProgram) -> list:
    problems = []
    where = f"функция {fn.name}"
    types = fn.var_types()

    if not fn.blocks:
        return [f"{where}: нет блоков"]

    labels = [b.label for b in fn.blocks]
    if len(set(labels)) != len(labels):
        problems.append(f"{where}: повторяющиеся метки блоков")
    label_set = set(labels)

    def ty(x):
        if is_const(x):
            return INT
        return types.get(x)

    def need(ins_text, x, expected, what):
        actual = ty(x)
        if actual is None:
            problems.append(f"{where}: {ins_text}: неизвестное имя {x!r}")
        elif actual != expected:
            problems.append(f"{where}: {ins_text}: {what} {x!r} имеет тип {actual}, ожидался {expected}")

    for block in fn.blocks:
        if not block.instrs:
            problems.append(f"{where}: блок {block.label} пуст")
            continue
        for k, ins in enumerate(block.instrs):
            text = f"[{block.label}] {format_instr(ins)}" if ins.op != "label" else ins.op
            is_last = k == len(block.instrs) - 1
            if ins.op in TERMINATORS and not is_last:
                problems.append(f"{where}: {text}: терминатор не в конце блока")
            if is_last and ins.op not in TERMINATORS:
                problems.append(f"{where}: блок {block.label} не завершён терминатором")

            op = ins.op
            if op == "mov":
                need(text, ins.dsts[0], INT, "приёмник")
                need(text, ins.args[0], INT, "операнд")
            elif op == "copy":
                need(text, ins.dsts[0], INT_ARR, "приёмник")
                need(text, ins.args[0], INT_ARR, "операнд")
            elif op == "bin":
                if ins.operator not in BIN_OPS:
                    problems.append(f"{where}: {text}: неизвестный оператор {ins.operator!r}")
                need(text, ins.dsts[0], INT, "приёмник")
                for a in ins.args:
                    need(text, a, INT, "операнд")
            elif op in ("neg", "not"):
                need(text, ins.dsts[0], INT, "приёмник")
                need(text, ins.args[0], INT, "операнд")
            elif op == "aload":
                need(text, ins.dsts[0], INT, "приёмник")
                need(text, ins.args[0], INT_ARR, "массив")
                need(text, ins.args[1], INT, "индекс")
            elif op == "astore":
                need(text, ins.args[0], INT_ARR, "массив")
                need(text, ins.args[1], INT, "индекс")
                need(text, ins.args[2], INT, "значение")
                if ins.dsts != [ins.args[0]]:
                    problems.append(f"{where}: {text}: dsts должен совпадать с массивом")
            elif op == "len":
                need(text, ins.dsts[0], INT, "приёмник")
                need(text, ins.args[0], INT_ARR, "массив")
            elif op == "call":
                callee = program.get(ins.callee)
                if callee is None:
                    problems.append(f"{where}: {text}: неизвестная функция {ins.callee!r}")
                    continue
                if len(ins.args) != len(callee.params):
                    problems.append(f"{where}: {text}: число аргументов {len(ins.args)} != {len(callee.params)}")
                else:
                    for a, (_, pt) in zip(ins.args, callee.params):
                        need(text, a, pt, "аргумент")
                if len(ins.dsts) != len(callee.returns):
                    problems.append(f"{where}: {text}: число результатов {len(ins.dsts)} != {len(callee.returns)}")
                else:
                    for d, (_, rt) in zip(ins.dsts, callee.returns):
                        need(text, d, rt, "приёмник")
            elif op == "jump":
                if ins.targets[0] not in label_set:
                    problems.append(f"{where}: {text}: нет метки {ins.targets[0]!r}")
            elif op == "br":
                need(text, ins.args[0], INT, "условие")
                for t in ins.targets:
                    if t not in label_set:
                        problems.append(f"{where}: {text}: нет метки {t!r}")
            elif op == "ret":
                if len(ins.args) != len(fn.returns):
                    problems.append(f"{where}: {text}: число значений {len(ins.args)} != {len(fn.returns)}")
                else:
                    for a, (_, rt) in zip(ins.args, fn.returns):
                        need(text, a, rt, "значение")
            else:
                problems.append(f"{where}: {text}: неизвестная операция {op!r}")
    return problems


def validate_program(program: IRProgram) -> list:
    problems = []
    for fn in program.functions:
        problems.extend(validate_function(fn, program))
    return problems
