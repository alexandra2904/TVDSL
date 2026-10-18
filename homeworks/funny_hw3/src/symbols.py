from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str                
    type: object              
    pos: int
    declared: bool = True    
    inferred_at: int | None = None   


@dataclass
class FuncSig:
    name: str
    params: list             
    returns: list            
    pos: int
    is_formula: bool = False
    builtin: bool = False


class Scope:
    def __init__(self, parent: "Scope | None" = None):
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    def declare(self, sym: Symbol) -> Symbol | None:
        existing = self.symbols.get(sym.name)
        if existing is not None:
            return existing
        self.symbols[sym.name] = sym
        return None

    def lookup(self, name: str) -> Symbol | None:
        scope: Scope | None = self
        while scope is not None:
            if name in scope.symbols:
                return scope.symbols[name]
            scope = scope.parent
        return None
