from __future__ import annotations

from ir import IRFunction, IRProgram, is_const, INT_ARR
from optimize import wrap32, eval_bin


class IRRuntimeError(Exception):
    """Ошибка времени выполнения Funny (деление на ноль, выход за границы массива, ...)."""


class Machine:
    def __init__(self, program: IRProgram, max_steps: int = 2_000_000):
        self.program = program
        self.max_steps = max_steps
        self.steps = 0

    def run(self, name: str, args: list) -> list:
        fn = self.program.get(name)
        if fn is None:
            raise IRRuntimeError(f"нет функции '{name}'")
        if len(args) != len(fn.params):
            raise IRRuntimeError(f"функция '{name}' ожидает аргументов: {len(fn.params)}, передано: {len(args)}")
        return self._call(fn, args)


    def _call(self, fn: IRFunction, args: list) -> list:
        frame = {}
        for (pname, ptype), value in zip(fn.params, args):
            frame[pname] = list(value) if ptype == INT_ARR else wrap32(value)
        for name, ty in fn.returns + fn.locals:
            frame.setdefault(name, [] if ty == INT_ARR else 0)

        blocks = {b.label: b for b in fn.blocks}
        block = fn.blocks[0]

        def val(x):
            if is_const(x):
                return x
            if x not in frame:
                raise IRRuntimeError(f"{fn.name}: чтение неопределённого значения '{x}'")
            return frame[x]

        while True:
            for ins in block.instrs:
                self.steps += 1
                if self.steps > self.max_steps:
                    raise IRRuntimeError("превышен лимит шагов выполнения")
                op = ins.op

                if op == "mov":
                    frame[ins.dsts[0]] = val(ins.args[0])
                elif op == "copy":
                    frame[ins.dsts[0]] = list(val(ins.args[0]))
                elif op == "bin":
                    a, b = val(ins.args[0]), val(ins.args[1])
                    result = eval_bin(ins.operator, a, b)
                    if result is None:
                        raise IRRuntimeError("деление на ноль")
                    frame[ins.dsts[0]] = result
                elif op == "neg":
                    frame[ins.dsts[0]] = wrap32(-val(ins.args[0]))
                elif op == "not":
                    frame[ins.dsts[0]] = 1 if val(ins.args[0]) == 0 else 0
                elif op == "aload":
                    arr, i = val(ins.args[0]), val(ins.args[1])
                    if not 0 <= i < len(arr):
                        raise IRRuntimeError("выход за границы массива")
                    frame[ins.dsts[0]] = arr[i]
                elif op == "astore":
                    arr, i, v = val(ins.args[0]), val(ins.args[1]), val(ins.args[2])
                    if not 0 <= i < len(arr):
                        raise IRRuntimeError("выход за границы массива")
                    arr[i] = v
                elif op == "len":
                    frame[ins.dsts[0]] = len(val(ins.args[0]))
                elif op == "call":
                    callee = self.program.get(ins.callee)
                    if callee is None:
                        raise IRRuntimeError(f"вызов неизвестной функции '{ins.callee}'")
                    results = self._call(callee, [val(a) for a in ins.args])
                    for d, r in zip(ins.dsts, results):
                        frame[d] = r
                elif op == "jump":
                    block = blocks[ins.targets[0]]
                    break
                elif op == "br":
                    block = blocks[ins.targets[0] if val(ins.args[0]) != 0 else ins.targets[1]]
                    break
                elif op == "ret":
                    return [val(a) for a in ins.args]
                else:
                    raise IRRuntimeError(f"неизвестная операция {op}")
            else:
                raise IRRuntimeError(f"{fn.name}: блок {block.label} не завершён")


def run_function(program: IRProgram, name: str, args: list, max_steps: int = 2_000_000) -> list:
    return Machine(program, max_steps).run(name, args)
