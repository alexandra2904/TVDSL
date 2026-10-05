from __future__ import annotations

from ast_nodes import (
    VariableDef, LocalVarDef,
    IntLiteral, BoolLiteral, Var, ArrayAccess, Call, UnaryOp, BinOp, Quantifier,
    Block, If, While, Assert, Assume, SimpleAssign, ArrayAssign, TupleAssign,
    FunctionDef, FormulaDef, Module,
)


class ParserError(Exception):

    def __init__(self, message: str, pos: int):
        super().__init__(message)
        self.message = message
        self.pos = pos

    def __str__(self):
        return f"{self.message} (позиция {self.pos})"


def offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last_nl = text.rfind("\n", 0, offset)
    col = offset - last_nl
    return line, col


_TOP_LEVEL_START = {"IDENT"}

_STMT_SYNC = {"SEMICOLON", "RBRACE"}


class Parser:
    def __init__(self, tokens: list, text: str = ""):
        self.tokens = tokens
        self.text = text
        self.pos = 0  
        self.errors: list[ParserError] = []

    def _current(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _peek_name(self):
        tok = self._current()
        return tok.name if tok is not None else "EOF"

    def _peek_pos(self):
        tok = self._current()
        if tok is not None:
            return tok.start
        return self.tokens[-1].end if self.tokens else 0

    def _advance(self):
        tok = self._current()
        if tok is not None:
            self.pos += 1
        return tok

    def _check(self, name: str) -> bool:
        return self._peek_name() == name

    def _check_any(self, names) -> bool:
        return self._peek_name() in names

    def _expect(self, name: str):
        if self._check(name):
            return self._advance()
        raise ParserError(
            f"ожидался токен {name}, но встречен {self._peek_name()}",
            self._peek_pos(),
        )


    def parse_module(self) -> Module:
        module = Module()
        if not self.tokens:
            self.errors.append(ParserError("пустой вход: ожидалась хотя бы одна функция или формула", 0))
            return module

        while self._current() is not None:
            start_pos = self.pos
            try:
                defn = self._parse_function_or_formula()
                if isinstance(defn, FunctionDef):
                    module.functions.append(defn)
                else:
                    module.formulas.append(defn)
            except ParserError as err:
                self.errors.append(err)
                self._synchronize_top_level(start_pos)
        return module


    def _synchronize_top_level(self, start_pos: int):
        if self.pos == start_pos:
            self._advance()
        depth = 0
        while self._current() is not None:
            name = self._peek_name()
            if name in ("LPAREN", "LBRACE"):
                depth += 1
            elif name in ("RPAREN", "RBRACE"):
                depth = max(0, depth - 1)
            elif depth == 0 and name in _TOP_LEVEL_START:
                return
            self._advance()


    def _parse_function_or_formula(self):
        is_function = self._check("FUNCTION")
        if is_function:
            self._advance()

        name_tok = self._expect("IDENT")
        self._expect("LPAREN")
        params = self._parse_variable_def_list()
        self._expect("RPAREN")

        if not is_function:
            self._expect("FATARROW")
            body = self._parse_expr()
            self._expect("SEMICOLON")
            return FormulaDef(name_tok.lexeme, params, body, name_tok.start)

        requires = None
        if self._check("REQUIRES"):
            self._advance()
            requires = self._parse_expr()

        if not self._check("RETURNS"):
            raise ParserError(
                "ожидался 'returns' (определение функции) или '=>' (определение формулы), "
                f"встречен {self._peek_name()}",
                self._peek_pos(),
            )
        self._advance()
        returns = self._parse_variable_def_list_nonempty()

        ensures = None
        if self._check("ENSURES"):
            self._advance()
            ensures = self._parse_expr()

        uses: list[LocalVarDef] = []
        if self._check("USES"):
            self._advance()
            uses = self._parse_local_var_def_list_nonempty()

        body = self._parse_statement()
        return FunctionDef(name_tok.lexeme, params, requires, returns, ensures, uses, body, name_tok.start)

    def _parse_variable_def_list(self) -> list[VariableDef]:
        if self._check("RPAREN"):
            return []
        return self._parse_variable_def_list_nonempty()

    def _parse_variable_def_list_nonempty(self) -> list[VariableDef]:
        defs = [self._parse_variable_def()]
        while self._check("COMMA"):
            self._advance()
            defs.append(self._parse_variable_def())
        return defs

    def _parse_variable_def(self) -> VariableDef:
        name_tok = self._expect("IDENT")
        self._expect("COLON")
        vtype = self._parse_variable_type()
        return VariableDef(name_tok.lexeme, vtype, name_tok.start)

    def _parse_variable_type(self) -> str:
        self._expect("INT_TYPE")
        if self._check("LBRACKET"):
            self._advance()
            self._expect("RBRACKET")
            return "int[]"
        return "int"

    def _parse_local_var_def_list_nonempty(self) -> list[LocalVarDef]:
        defs = [self._parse_local_var_def()]
        while self._check("COMMA"):
            self._advance()
            defs.append(self._parse_local_var_def())
        return defs

    def _parse_local_var_def(self) -> LocalVarDef:
        name_tok = self._expect("IDENT")
        vtype = None
        if self._check("COLON"):
            self._advance()
            vtype = self._parse_variable_type()
        return LocalVarDef(name_tok.lexeme, vtype, name_tok.start)


    def _parse_statement(self):
        name = self._peek_name()
        if name == "LBRACE":
            return self._parse_block()
        if name == "IF":
            return self._parse_if()
        if name == "WHILE":
            return self._parse_while()
        if name == "ASSERT":
            return self._parse_assert()
        if name == "ASSUME":
            return self._parse_assume()
        if name == "IDENT":
            return self._parse_assignment_or_array_update()
        raise ParserError(f"ожидался оператор, встречен {name}", self._peek_pos())

    def _parse_statement_recovering(self):
        start_pos = self.pos
        try:
            return self._parse_statement()
        except ParserError as err:
            self.errors.append(err)
            if self.pos == start_pos:
                self._advance()
            while self._current() is not None and not self._check_any(_STMT_SYNC):
                self._advance()
            if self._check("SEMICOLON"):
                self._advance()
            return None

    def _parse_block(self) -> Block:
        lbrace = self._expect("LBRACE")
        statements = []
        while self._current() is not None and not self._check("RBRACE"):
            stmt = self._parse_statement_recovering()
            if stmt is not None:
                statements.append(stmt)
        self._expect("RBRACE")
        return Block(statements, lbrace.start)

    def _parse_if(self) -> If:
        kw = self._expect("IF")
        self._expect("LPAREN")
        condition = self._parse_expr()
        self._expect("RPAREN")
        then_branch = self._parse_statement()
        else_branch = None
        if self._check("ELSE"):
            self._advance()
            else_branch = self._parse_statement()
        return If(condition, then_branch, else_branch, kw.start)

    def _parse_while(self) -> While:
        kw = self._expect("WHILE")
        self._expect("LPAREN")
        condition = self._parse_expr()
        self._expect("RPAREN")
        invariant = None
        if self._check("INVARIANT"):
            self._advance()
            invariant = self._parse_expr()
        body = self._parse_statement()
        return While(condition, invariant, body, kw.start)

    def _parse_assert(self) -> Assert:
        kw = self._expect("ASSERT")
        pred = self._parse_expr()
        self._expect("SEMICOLON")
        return Assert(pred, kw.start)

    def _parse_assume(self) -> Assume:
        kw = self._expect("ASSUME")
        pred = self._parse_expr()
        self._expect("SEMICOLON")
        return Assume(pred, kw.start)

    def _parse_assignment_or_array_update(self):
        name_tok = self._expect("IDENT")

        if self._check("LBRACKET"):
            target = Var(name_tok.lexeme, name_tok.start)
            while self._check("LBRACKET"):
                self._advance()
                index = self._parse_expr()
                self._expect("RBRACKET")
                target = ArrayAccess(target, index, name_tok.start)
            self._expect("ASSIGN")
            value = self._parse_expr()
            self._expect("SEMICOLON")
            return ArrayAssign(target, value, name_tok.start)

        targets = [name_tok.lexeme]
        while self._check("COMMA"):
            self._advance()
            targets.append(self._expect("IDENT").lexeme)
        self._expect("ASSIGN")

        if len(targets) == 1:
            value = self._parse_expr()
            self._expect("SEMICOLON")
            return SimpleAssign(targets[0], value, name_tok.start)

        call = self._parse_call_expr()
        self._expect("SEMICOLON")
        return TupleAssign(targets, call, name_tok.start)


    def _parse_expr(self):
        return self._parse_implies()

    def _parse_implies(self):
        left = self._parse_or()
        if self._check("ARROW"):
            arrow = self._advance()
            right = self._parse_implies()  
            return BinOp("->", left, right, arrow.start)
        return left

    def _parse_or(self):
        left = self._parse_and()
        while self._check("OR"):
            op = self._advance()
            right = self._parse_and()
            left = BinOp("or", left, right, op.start)
        return left

    def _parse_and(self):
        left = self._parse_not()
        while self._check("AND"):
            op = self._advance()
            right = self._parse_not()
            left = BinOp("and", left, right, op.start)
        return left

    def _parse_not(self):
        if self._check("NOT"):
            op = self._advance()
            operand = self._parse_not()
            return UnaryOp("not", operand, op.start)
        return self._parse_comparison()

    _COMPARISON_OPS = {
        "EQ": "==", "NE": "!=", "GE": ">=", "LE": "<=", "GT": ">", "LT": "<",
    }

    def _parse_comparison(self):
        left = self._parse_additive()
        if self._check_any(self._COMPARISON_OPS):
            op_tok = self._advance()
            right = self._parse_additive()
            return BinOp(self._COMPARISON_OPS[op_tok.name], left, right, op_tok.start)
        return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._check_any(("PLUS", "MINUS")):
            op_tok = self._advance()
            right = self._parse_multiplicative()
            op = "+" if op_tok.name == "PLUS" else "-"
            left = BinOp(op, left, right, op_tok.start)
        return left

    def _parse_multiplicative(self):
        left = self._parse_unary()
        while self._check_any(("STAR", "SLASH")):
            op_tok = self._advance()
            right = self._parse_unary()
            op = "*" if op_tok.name == "STAR" else "/"
            left = BinOp(op, left, right, op_tok.start)
        return left

    def _parse_unary(self):
        if self._check("MINUS"):
            op = self._advance()
            operand = self._parse_unary()
            return UnaryOp("-", operand, op.start)
        return self._parse_atom()

    def _parse_atom(self):
        name = self._peek_name()

        if name == "TRUE":
            tok = self._advance()
            return BoolLiteral(True, tok.start)
        if name == "FALSE":
            tok = self._advance()
            return BoolLiteral(False, tok.start)

        if name in ("FORALL", "EXISTS"):
            return self._parse_quantifier()

        if name == "LPAREN":
            self._advance()
            inner = self._parse_expr()
            self._expect("RPAREN")
            return inner

        if name == "INT":
            tok = self._advance()
            return IntLiteral(int(tok.lexeme), tok.start)

        if name == "IDENT":
            return self._parse_ident_atom()

        if name == "LENGTH":
            tok = self._advance()
            self._expect("LPAREN")
            args = []
            if not self._check("RPAREN"):
                args.append(self._parse_expr())
                while self._check("COMMA"):
                    self._advance()
                    args.append(self._parse_expr())
            self._expect("RPAREN")
            return Call("length", args, tok.start)

        raise ParserError(f"ожидалось выражение, встречен {name}", self._peek_pos())

    def _parse_ident_atom(self):
        next_tok = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        if next_tok is not None and next_tok.name == "LPAREN":
            return self._parse_call_expr()

        name_tok = self._expect("IDENT")
        node = Var(name_tok.lexeme, name_tok.start)
        while self._check("LBRACKET"):
            self._advance()
            index = self._parse_expr()
            self._expect("RBRACKET")
            node = ArrayAccess(node, index, name_tok.start)
        return node

    def _parse_call_expr(self) -> Call:
        name_tok = self._expect("IDENT")
        self._expect("LPAREN")
        args = []
        if not self._check("RPAREN"):
            args.append(self._parse_expr())
            while self._check("COMMA"):
                self._advance()
                args.append(self._parse_expr())
        self._expect("RPAREN")
        return Call(name_tok.lexeme, args, name_tok.start)

    def _parse_quantifier(self) -> Quantifier:
        kind_tok = self._advance()  
        kind = "forall" if kind_tok.name == "FORALL" else "exists"
        self._expect("LPAREN")
        var = self._parse_variable_def()
        self._expect("PIPE")
        body = self._parse_expr()
        self._expect("RPAREN")
        return Quantifier(kind, var, body, kind_tok.start)


def parse(tokens: list, text: str = "") -> tuple[Module, list[ParserError]]:
    parser = Parser(tokens, text)
    module = parser.parse_module()
    return module, parser.errors
