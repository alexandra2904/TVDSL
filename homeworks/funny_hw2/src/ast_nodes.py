from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VariableDef:
    name: str
    type: str        
    pos: int


@dataclass
class LocalVarDef:
    name: str
    type: str | None   
    pos: int


class Expr:
    pos: int


@dataclass
class IntLiteral(Expr):
    value: int
    pos: int


@dataclass
class BoolLiteral(Expr):
    value: bool
    pos: int


@dataclass
class Var(Expr):
    name: str
    pos: int


@dataclass
class ArrayAccess(Expr):
    base: Expr
    index: Expr
    pos: int


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]
    pos: int


@dataclass
class UnaryOp(Expr):
    op: str           
    operand: Expr
    pos: int


@dataclass
class BinOp(Expr):
    op: str            
    left: Expr
    right: Expr
    pos: int


@dataclass
class Quantifier(Expr):
    kind: str           
    var: VariableDef
    body: Expr
    pos: int



class Stmt:
    pos: int


@dataclass
class Block(Stmt):
    statements: list[Stmt]
    pos: int


@dataclass
class If(Stmt):
    condition: Expr
    then_branch: Stmt
    else_branch: Stmt | None
    pos: int


@dataclass
class While(Stmt):
    condition: Expr
    invariant: Expr | None
    body: Stmt
    pos: int


@dataclass
class Assert(Stmt):
    predicate: Expr
    pos: int


@dataclass
class Assume(Stmt):
    predicate: Expr
    pos: int


@dataclass
class SimpleAssign(Stmt):
    target: str
    value: Expr
    pos: int


@dataclass
class ArrayAssign(Stmt):
    target: ArrayAccess
    value: Expr
    pos: int


@dataclass
class TupleAssign(Stmt):
    targets: list[str]
    call: Call
    pos: int


@dataclass
class FunctionDef:
    name: str
    params: list[VariableDef]
    requires: Expr | None
    returns: list[VariableDef]
    ensures: Expr | None
    uses: list[LocalVarDef]
    body: Stmt
    pos: int


@dataclass
class FormulaDef:
    name: str
    params: list[VariableDef]
    body: Expr
    pos: int


@dataclass
class Module:
    functions: list[FunctionDef] = field(default_factory=list)
    formulas: list[FormulaDef] = field(default_factory=list)



def to_dict(node):
    if node is None:
        return None
    if isinstance(node, list):
        return [to_dict(x) for x in node]
    if isinstance(node, (str, int, bool)):
        return node
    if hasattr(node, "__dataclass_fields__"):
        result = {"node": type(node).__name__}
        for field_name in node.__dataclass_fields__:
            result[field_name] = to_dict(getattr(node, field_name))
        return result
    raise TypeError(f"cannot serialize AST node of type {type(node)!r}")
