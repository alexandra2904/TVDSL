from __future__ import annotations

INT = "int"
INT_ARR = "int[]"
BOOL = "bool"
ERROR = "<error>"


class TypeVar:

    _counter = 0

    def __init__(self):
        TypeVar._counter += 1
        self.id = TypeVar._counter
        self.ref = None

    def __repr__(self):
        return f"?T{self.id}" if self.ref is None else repr(self.ref)


def prune(t):
    while isinstance(t, TypeVar) and t.ref is not None:
        t = t.ref
    return t


def is_unbound(t) -> bool:
    return isinstance(prune(t), TypeVar)


def unify(a, b) -> bool:
    a, b = prune(a), prune(b)
    if a is b:
        return True
    if isinstance(a, TypeVar):
        a.ref = b
        return True
    if isinstance(b, TypeVar):
        b.ref = a
        return True
    if a == ERROR or b == ERROR:
        return True
    return a == b


def show(t) -> str:
    t = prune(t)
    if isinstance(t, TypeVar):
        return "?"
    return t
