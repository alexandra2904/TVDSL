from __future__ import annotations

from ast_nodes import (
    VariableDef, LocalVarDef,
    IntLiteral, BoolLiteral, Var, ArrayAccess, Call, UnaryOp, BinOp, Quantifier,
    Block, If, While, Assert, Assume, SimpleAssign, ArrayAssign, TupleAssign,
    FunctionDef, FormulaDef, Module,
)
from parser import offset_to_line_col
from symbols import Symbol, FuncSig, Scope
from typesys import INT, INT_ARR, BOOL, ERROR, TypeVar, prune, is_unbound, unify, show


class SemanticError:
    def __init__(self, message: str, pos: int):
        self.message = message
        self.pos = pos

    def __str__(self):
        return f"{self.message} (позиция {self.pos})"


KIND_RU = {
    "param": "параметр",
    "return": "возвращаемое значение",
    "local": "локальная переменная",
    "quantifier": "переменная квантора",
}

AREA_DESC = {
    "requires": "там доступны только параметры",
    "ensures": "там доступны параметры и возвращаемые значения",
    "formula": "там доступны только параметры формулы",
    "body": "там доступны параметры, возвращаемые значения и локальные переменные",
}

_ARITH = {"+", "-", "*", "/"}
_CMP = {"==", "!=", ">=", "<=", ">", "<"}
_LOGIC = {"and", "or", "->"}


def start_of(node) -> int:
    while isinstance(node, BinOp):
        node = node.left
    return node.pos


class Checker:
    def __init__(self, text: str = ""):
        self.text = text
        self.errors: list[SemanticError] = []
        self.functions: dict[str, FuncSig] = {
            "length": FuncSig("length", [("a", INT_ARR)], [INT], -1, builtin=True)
        }
        self.scope: Scope | None = None
        self.visible: set[str] = set()
        self.area = "body"
        self.fn_syms: list[Symbol] = []


    def error(self, message: str, pos: int):
        self.errors.append(SemanticError(message, pos))

    def _loc(self, pos: int) -> str:
        line, col = offset_to_line_col(self.text, pos)
        return f"{line}:{col}"

    def _set_area(self, area: str, visible: set[str]):
        self.area = area
        self.visible = visible

    def _require(self, t, expected: str, node, what: str):
        if t != ERROR and t != expected:
            self.error(f"{what}: ожидался {expected}, получен {t}", start_of(node))

    def _expect_bool(self, node, allow_pred: bool, what: str):
        t = self.expr(node, allow_pred)
        self._require(t, BOOL, node, what)


    def check_module(self, module: Module) -> list[SemanticError]:
        items = sorted(list(module.functions) + list(module.formulas), key=lambda d: d.pos)
        for item in items:
            self._register(item)
        for item in items:
            if isinstance(item, FunctionDef):
                self._check_function(item)
            else:
                self._check_formula(item)
        self.errors.sort(key=lambda e: e.pos)
        return self.errors

    def _register(self, d):
        is_formula = isinstance(d, FormulaDef)
        existing = self.functions.get(d.name)
        if existing is not None:
            where = "" if existing.builtin else f" (первое определение: {self._loc(existing.pos)})"
            self.error(f"повторное определение '{d.name}'{where}", d.pos)
            return
        returns = [] if is_formula else [r.type for r in d.returns]
        self.functions[d.name] = FuncSig(
            d.name, [(p.name, p.type) for p in d.params], returns, d.pos, is_formula
        )


    def _declare(self, name, kind, type_, pos, declared) -> Symbol | None:
        sym = Symbol(name, kind, type_, pos, declared)
        prev = self.scope.declare(sym)
        if prev is not None:
            self.error(
                f"повторное объявление '{name}' ({KIND_RU[kind]}); "
                f"имя уже объявлено как {KIND_RU[prev.kind]} в {self._loc(prev.pos)}",
                pos,
            )
            return None
        self.fn_syms.append(sym)
        return sym

    def _symbol_table(self) -> list[dict]:
        return [
            {
                "name": s.name,
                "kind": s.kind,
                "type": show(s.type),
                "declared": s.declared,
                "pos": s.pos,
            }
            for s in self.fn_syms
        ]

    def _check_function(self, fn: FunctionDef):
        self.scope = Scope()
        self.fn_syms = []

        for p in fn.params:
            self._declare(p.name, "param", p.type, p.pos, True)
        for r in fn.returns:
            self._declare(r.name, "return", r.type, r.pos, True)
        local_syms = []
        for u in fn.uses:
            declared = u.type is not None
            sym = self._declare(u.name, "local", u.type if declared else TypeVar(), u.pos, declared)
            local_syms.append((u, sym))

        if fn.requires is not None:
            self._set_area("requires", {"param"})
            self._expect_bool(fn.requires, True, "условие requires")
        if fn.ensures is not None:
            self._set_area("ensures", {"param", "return"})
            self._expect_bool(fn.ensures, True, "условие ensures")

        self._set_area("body", {"param", "return", "local"})
        self._stmt(fn.body)

        for u, sym in local_syms:
            if sym is None:           
                u.ty = u.type if u.type else ERROR
                continue
            if is_unbound(sym.type):
                self.error(
                    f"не удалось вывести тип локальной переменной '{u.name}': "
                    f"ей нет ни одного присваивания, а аннотации типа нет",
                    u.pos,
                )
                unify(sym.type, ERROR)
            u.ty = show(sym.type)

        fn.symbols = self._symbol_table()

    def _check_formula(self, fm: FormulaDef):
        self.scope = Scope()
        self.fn_syms = []
        for p in fm.params:
            self._declare(p.name, "param", p.type, p.pos, True)
        self._set_area("formula", {"param"})
        self._expect_bool(fm.body, True, "тело формулы")
        fm.symbols = self._symbol_table()


    def _lookup(self, name: str, pos: int) -> Symbol | None:
        sym = self.scope.lookup(name)
        if sym is None:
            self.error(f"неизвестное имя '{name}'", pos)
            return None
        if sym.kind != "quantifier" and sym.kind not in self.visible:
            self.error(
                f"'{name}' ({KIND_RU[sym.kind]}) недоступно в {self.area}: {AREA_DESC[self.area]}",
                pos,
            )
            return None
        return sym

    def _assignable(self, sym: Symbol, name: str, pos: int, element: bool = False) -> bool:
        if sym.kind == "param":
            if element:
                self.error(
                    f"параметр-массив '{name}' доступен только для чтения: "
                    f"{name}[i] = v означает {name} = set({name}, i, v), т.е. присваивание параметру",
                    pos,
                )
            else:
                self.error(f"параметр '{name}' доступен только для чтения, присваивать ему нельзя", pos)
            return False
        return True


    def _assign(self, sym: Symbol, name: str, t, pos: int):
        if t == ERROR:
            unify(sym.type, ERROR)
            return
        if t == BOOL:
            self.error(
                f"нельзя присвоить значение типа bool переменной '{name}': "
                f"в Funny нет переменных типа bool",
                pos,
            )
            unify(sym.type, ERROR)
            return
        was_free = is_unbound(sym.type)
        before = show(sym.type)
        if unify(sym.type, t):
            if was_free:
                sym.inferred_at = pos
            return
        hint = (
            f" (тип выведен из первого присваивания в {self._loc(sym.inferred_at)})"
            if sym.inferred_at is not None
            else ""
        )
        self.error(
            f"несовместимые типы: переменная '{name}' имеет тип {before}{hint}, "
            f"а присваивается значение типа {t}",
            pos,
        )


    def _stmt(self, s):
        if isinstance(s, Block):
            for st in s.statements:
                self._stmt(st)

        elif isinstance(s, If):
            t = self.expr(s.condition, False)
            self._require(t, BOOL, s.condition, "условие if")
            self._stmt(s.then_branch)
            if s.else_branch is not None:
                self._stmt(s.else_branch)

        elif isinstance(s, While):
            t = self.expr(s.condition, False)
            self._require(t, BOOL, s.condition, "условие while")
            if s.invariant is not None:
                self._expect_bool(s.invariant, True, "инвариант while")
            self._stmt(s.body)

        elif isinstance(s, Assert):
            self._expect_bool(s.predicate, True, "условие assert")

        elif isinstance(s, Assume):
            self._expect_bool(s.predicate, True, "условие assume")

        elif isinstance(s, SimpleAssign):
            self._simple_assign(s)

        elif isinstance(s, ArrayAssign):
            self._array_assign(s)

        elif isinstance(s, TupleAssign):
            self._tuple_assign(s)

    def _simple_assign(self, s: SimpleAssign):
        vt = self.expr(s.value, False)
        sym = self._lookup(s.target, s.pos)
        if sym is None:
            return
        if not self._assignable(sym, s.target, s.pos):
            return
        self._assign(sym, s.target, vt, start_of(s.value))

    def _array_assign(self, s: ArrayAssign):
        tgt = s.target
        vt = self.expr(s.value, False)
        it = self.expr(tgt.index, False)
        self._require(it, INT, tgt.index, "индекс массива")
        self._require(vt, INT, s.value, "элементу массива можно присвоить только int")

        base = tgt.base
        if not isinstance(base, Var):
            self.expr(base, False)
            self.error(
                "многомерные массивы не поддерживаются: у int[] можно индексировать один раз",
                tgt.pos,
            )
            tgt.ty = ERROR
            return

        sym = self._lookup(base.name, base.pos)
        if sym is None:
            base.ty = tgt.ty = ERROR
            return
        if not self._assignable(sym, base.name, base.pos, element=True):
            base.ty = show(sym.type)
            tgt.ty = INT
            return
        was_free = is_unbound(sym.type)
        before = show(sym.type)
        if unify(sym.type, INT_ARR):
            if was_free:
                sym.inferred_at = base.pos
        else:
            self.error(
                f"индексировать можно только int[], а '{base.name}' имеет тип {before}",
                base.pos,
            )
        base.ty = show(sym.type)
        tgt.ty = INT

    def _tuple_assign(self, s: TupleAssign):
        sig = self._call(s.call)
        names = s.targets

        def poison():
            for n in names:
                sym = self.scope.lookup(n)
                if sym is not None:
                    unify(sym.type, ERROR)

        if sig is None:
            s.call.ty = ERROR
            poison()
            return
        if sig.is_formula:
            self.error(
                f"'{sig.name}' -- формула, она не возвращает значений для присваивания",
                s.call.pos,
            )
            s.call.ty = ERROR
            poison()
            return
        s.call.ty = "(" + ", ".join(sig.returns) + ")"
        if len(names) != len(sig.returns):
            self.error(
                f"функция '{sig.name}' возвращает значений: {len(sig.returns)}, "
                f"а слева указано переменных: {len(names)}",
                s.pos,
            )
            poison()
            return

        seen = set()
        for name, rt in zip(names, sig.returns):
            if name in seen:
                self.error(f"переменная '{name}' повторяется в левой части присваивания", s.pos)
                continue
            seen.add(name)
            sym = self._lookup(name, s.pos)
            if sym is None:
                continue
            if not self._assignable(sym, name, s.pos):
                continue
            self._assign(sym, name, rt, s.pos)


    def _call(self, node: Call) -> FuncSig | None:
        arg_types = [self.expr(a, False) for a in node.args]
        sig = self.functions.get(node.name)
        if sig is None:
            self.error(f"неизвестная функция или формула '{node.name}'", node.pos)
            return None
        if len(node.args) != len(sig.params):
            self.error(
                f"'{node.name}' ожидает аргументов: {len(sig.params)}, передано: {len(node.args)}",
                node.pos,
            )
            return sig
        for i, (arg, at, (_pname, pt)) in enumerate(zip(node.args, arg_types, sig.params), 1):
            if at != ERROR and at != pt:
                self.error(
                    f"аргумент {i} вызова '{node.name}': ожидался {pt}, получен {at}",
                    start_of(arg),
                )
        return sig


    def expr(self, node, allow_pred: bool) -> str:
        t = self._expr(node, allow_pred)
        node.ty = t
        return t

    def _expr(self, node, allow_pred: bool) -> str:
        if isinstance(node, IntLiteral):
            return INT
        if isinstance(node, BoolLiteral):
            return BOOL
        if isinstance(node, Var):
            return self._var(node)
        if isinstance(node, ArrayAccess):
            return self._array_access(node)
        if isinstance(node, Call):
            return self._call_expr(node, allow_pred)
        if isinstance(node, UnaryOp):
            return self._unary(node, allow_pred)
        if isinstance(node, BinOp):
            return self._binary(node, allow_pred)
        if isinstance(node, Quantifier):
            return self._quantifier(node, allow_pred)
        raise TypeError(f"неизвестный узел выражения: {type(node).__name__}")

    def _var(self, node: Var) -> str:
        sym = self._lookup(node.name, node.pos)
        if sym is None:
            return ERROR
        t = prune(sym.type)
        if isinstance(t, TypeVar):
            self.error(
                f"локальная переменная '{node.name}' используется до первого присваивания: "
                f"её тип ещё не выведен",
                node.pos,
            )
            return ERROR
        return t

    def _array_access(self, node: ArrayAccess) -> str:
        bt = self.expr(node.base, False)
        it = self.expr(node.index, False)
        if bt != ERROR and bt != INT_ARR:
            hint = " (многомерные массивы не поддерживаются)" if isinstance(node.base, ArrayAccess) else ""
            self.error(f"индексировать можно только int[], получен {bt}{hint}", node.pos)
        self._require(it, INT, node.index, "индекс массива")
        return INT

    def _call_expr(self, node: Call, allow_pred: bool) -> str:
        sig = self._call(node)
        if sig is None:
            return ERROR
        if sig.is_formula:
            if not allow_pred:
                self.error(
                    f"формулу '{node.name}' можно использовать только в предикате "
                    f"(requires, ensures, invariant, assert, assume, тело формулы)",
                    node.pos,
                )
                return ERROR
            return BOOL
        if len(sig.returns) != 1:
            self.error(
                f"функция '{node.name}' возвращает значений: {len(sig.returns)}; в выражении "
                f"допустимо ровно одно (несколько значений -- только в присваивании x, y = f(...);)",
                node.pos,
            )
            return ERROR
        return sig.returns[0]

    def _unary(self, node: UnaryOp, allow_pred: bool) -> str:
        if node.op == "-":
            t = self.expr(node.operand, False)
            self._require(t, INT, node.operand, "операнд унарного минуса")
            return INT
        # not
        t = self.expr(node.operand, allow_pred)
        self._require(t, BOOL, node.operand, "операнд 'not'")
        return BOOL

    def _binary(self, node: BinOp, allow_pred: bool) -> str:
        op = node.op
        if op in _ARITH:
            lt = self.expr(node.left, False)
            rt = self.expr(node.right, False)
            self._require(lt, INT, node.left, f"левый операнд '{op}'")
            self._require(rt, INT, node.right, f"правый операнд '{op}'")
            return INT
        if op in _CMP:
            lt = self.expr(node.left, False)
            rt = self.expr(node.right, False)
            self._require(lt, INT, node.left, f"левый операнд '{op}'")
            self._require(rt, INT, node.right, f"правый операнд '{op}'")
            return BOOL
        lt = self.expr(node.left, allow_pred)
        rt = self.expr(node.right, allow_pred)
        self._require(lt, BOOL, node.left, f"левый операнд '{op}'")
        self._require(rt, BOOL, node.right, f"правый операнд '{op}'")
        return BOOL

    def _quantifier(self, node: Quantifier, allow_pred: bool) -> str:
        if not allow_pred:
            self.error(
                "кванторы forall/exists допустимы только в предикатах "
                "(requires, ensures, invariant, assert, assume, тело формулы)",
                node.pos,
            )
            return ERROR
        name = node.var.name
        existing = self.scope.lookup(name)
        if existing is not None and (existing.kind == "quantifier" or existing.kind in self.visible):
            self.error(
                f"имя переменной квантора '{name}' уже используется "
                f"({KIND_RU[existing.kind]}, {self._loc(existing.pos)}); "
                f"имя должно быть уникальным в области",
                node.var.pos,
            )
        outer = self.scope
        self.scope = Scope(outer)
        self.scope.declare(Symbol(name, "quantifier", node.var.type, node.var.pos, True))
        bt = self.expr(node.body, True)
        self._require(bt, BOOL, node.body, "тело квантора")
        self.scope = outer
        return BOOL


def check(module: Module, text: str = "") -> list[SemanticError]:
    return Checker(text).check_module(module)
