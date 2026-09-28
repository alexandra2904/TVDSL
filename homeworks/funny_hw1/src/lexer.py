from __future__ import annotations

from dataclasses import dataclass


class LexerError(Exception):
    pass


@dataclass
class Token:
    name: str
    lexeme: str
    start: int
    end: int

    def as_dict(self):
        return {
            "token": self.name,
            "lexeme": self.lexeme,
            "start": self.start,
            "end": self.end,
        }


class Lexer:
    def __init__(self, dfa, token_specs):
        self.dfa = dfa
        self.token_specs = token_specs
        self.char_to_index = {chr(c): i for i, c in enumerate(dfa.alphabet)}

    def _scan_one(self, text, start):
        state = self.dfa.start
        pos = start
        last_accept = None

        while pos < len(text):
            ch = text[pos]
            if ch not in self.char_to_index:
                break

            symbol = self.char_to_index[ch]
            state = self.dfa.transitions[state][symbol]
            pos += 1

            if state in self.dfa.accepting:
                last_accept = (pos, self.dfa.accepting[state])

            if state == self.dfa.trap:
                break

        if last_accept is None:
            bad = text[start:start + 1]
            code = ord(bad) if bad else None
            raise LexerError(
                f"unexpected character {bad!r} at position {start}; "
                f"ASCII code={code}"
            )

        end, token_index = last_accept
        return end, token_index

    def tokenize(self, text):
        result = []
        pos = 0

        while pos < len(text):
            end, token_index = self._scan_one(text, pos)
            spec = self.token_specs[token_index]
            token = Token(spec["name"], text[pos:end], pos, end)
            pos = end

            if not spec["skip"]:
                result.append(token)

        return result

    def accept_whole_token(self, text):
        """
        Checks whether the whole string is exactly one token.
        Useful for HW1 positive/negative token tests.
        """
        if text == "":
            return None

        try:
            end, token_index = self._scan_one(text, 0)
        except LexerError:
            return None

        if end != len(text):
            return None

        spec = self.token_specs[token_index]
        return spec["name"]
