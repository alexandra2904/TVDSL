from __future__ import annotations

from ast_nodes import (
    IntLiteral, BoolLiteral, Var, ArrayAccess, Call, UnaryOp, BinOp,
    Block, If, While, Assert, Assume, SimpleAssign, ArrayAssign, TupleAssign,
    FunctionDef, Module,
)
import ir
from ir import INT, INT_ARR, IRFunction, IRProgram

_CMP_AND_ARITH = set(ir.BIN_OPS)


def ir_type(ty: str) -> str:
    if ty == "int[]":
        return INT_ARR
    return INT


class FunctionGen:
    def __init__(self, fn: FunctionDef):
        if fn.symbols is None:
            raise ValueError(f"функция {fn.name}: нет таблицы символов, сначала нужна семантическая проверка (HW3)")
        self.fn = fn
        self.types = {s["name"]: s["type"] for s in fn.symbols}
        self.code = []
        self.temps = {}
        self.temp_count = 0
        self.label_count = 0


    def new_temp(self, ty: str) -> str:
        self.temp_count += 1
        name = f"%t{self.temp_count}"
        self.temps[name] = ty
        return name

    def new_label(self) -> str:
        self.label_count += 1
        return f"L{self.label_count}"

    def emit(self, instr):
        self.code.append(instr)

    def place(self, name: str):
        self.code.append(ir.label(name))


    def run(self) -> IRFunction:
        fn = self.fn
        self.place("entry")
        self.stmt(fn.body)
        self.emit(ir.ret([r.name for r in fn.returns]))
        return IRFunction(
            name=fn.name,
            params=[(p.name, p.type) for p in fn.params],
            returns=[(r.name, r.type) for r in fn.returns],
            locals=[(u.name, self.types[u.name]) for u in fn.uses],
            temps=self.temps,
            code=self.code,
        )


    def stmt(self, s):
        if isinstance(s, Block):
            for st in s.statements:
                self.stmt(st)
        elif isinstance(s, SimpleAssign):
            self.simple_assign(s)
        elif isinstance(s, ArrayAssign):
            arr = s.target.base.name
            idx = self.expr(s.target.index)
            val = self.expr(s.value)
            self.emit(ir.astore(arr, idx, val))
        elif isinstance(s, TupleAssign):
            args = [self.expr(a) for a in s.call.args]
            self.emit(ir.call(s.targets, s.call.name, args))
        elif isinstance(s, If):
            self.if_stmt(s)
        elif isinstance(s, While):
            self.while_stmt(s)
        elif isinstance(s, (Assert, Assume)):
            pass   
        else:
            raise TypeError(f"неизвестный оператор: {type(s).__name__}")

    def simple_assign(self, s: SimpleAssign):
        target_type = self.types[s.target]
        if target_type == INT_ARR:
            if isinstance(s.value, Var):
                self.emit(ir.copy_arr(s.target, s.value.name))   
            else:
                self.expr(s.value, dst=s.target)                 
            return
        operand = self.expr(s.value, dst=s.target)
        if operand != s.target:
            self.emit(ir.mov(s.target, operand))

    def if_stmt(self, s: If):
        cond = self.expr(s.condition)
        l_then, l_end = self.new_label(), self.new_label()
        l_else = self.new_label() if s.else_branch is not None else l_end
        self.emit(ir.br(cond, l_then, l_else))
        self.place(l_then)
        self.stmt(s.then_branch)
        self.emit(ir.jump(l_end))
        if s.else_branch is not None:
            self.place(l_else)
            self.stmt(s.else_branch)
            self.emit(ir.jump(l_end))
        self.place(l_end)

    def while_stmt(self, s: While):
        l_cond, l_body, l_end = self.new_label(), self.new_label(), self.new_label()
        self.emit(ir.jump(l_cond))
        self.place(l_cond)
        cond = self.expr(s.condition)
        self.emit(ir.br(cond, l_body, l_end))
        self.place(l_body)
        self.stmt(s.body)         
        self.emit(ir.jump(l_cond))
        self.place(l_end)


    def expr(self, node, dst=None):
        if isinstance(node, IntLiteral):
            return node.value
        if isinstance(node, BoolLiteral):
            return 1 if node.value else 0
        if isinstance(node, Var):
            return node.name
        if isinstance(node, ArrayAccess):
            arr = self.expr(node.base)
            idx = self.expr(node.index)
            d = dst or self.new_temp(INT)
            self.emit(ir.aload(d, arr, idx))
            return d
        if isinstance(node, Call):
            return self.call_expr(node, dst)
        if isinstance(node, UnaryOp):
            a = self.expr(node.operand)
            d = dst or self.new_temp(INT)
            self.emit(ir.neg(d, a) if node.op == "-" else ir.not_(d, a))
            return d
        if isinstance(node, BinOp):
            if node.op in _CMP_AND_ARITH:
                a = self.expr(node.left)
                b = self.expr(node.right)
                d = dst or self.new_temp(INT)
                self.emit(ir.binop(d, node.op, a, b))
                return d
            return self.logic(node)
        raise TypeError(f"выражение {type(node).__name__} не имеет исполняемой семантики")

    def call_expr(self, node: Call, dst):
        args = [self.expr(a) for a in node.args]
        if node.name == "length":
            d = dst or self.new_temp(INT)
            self.emit(ir.length(d, args[0]))
            return d
        d = dst or self.new_temp(ir_type(node.ty))
        self.emit(ir.call([d], node.name, args))
        return d

    def logic(self, node: BinOp):
        t = self.new_temp(INT)
        a = self.expr(node.left)
        l_rhs, l_end = self.new_label(), self.new_label()
        if node.op == "and":
            self.emit(ir.mov(t, a))
            self.emit(ir.br(t, l_rhs, l_end))
            self.place(l_rhs)
            self.emit(ir.mov(t, self.expr(node.right)))
            self.emit(ir.jump(l_end))
        elif node.op == "or":
            self.emit(ir.mov(t, a))
            self.emit(ir.br(t, l_end, l_rhs))
            self.place(l_rhs)
            self.emit(ir.mov(t, self.expr(node.right)))
            self.emit(ir.jump(l_end))
        else:   # a -> b
            l_true = self.new_label()
            self.emit(ir.br(a, l_rhs, l_true))
            self.place(l_rhs)
            self.emit(ir.mov(t, self.expr(node.right)))
            self.emit(ir.jump(l_end))
            self.place(l_true)
            self.emit(ir.mov(t, 1))
            self.emit(ir.jump(l_end))
        self.place(l_end)
        return t


def generate(module: Module) -> IRProgram:
    program = IRProgram()
    for fn in sorted(module.functions, key=lambda f: f.pos):
        program.functions.append(FunctionGen(fn).run())
    return program
