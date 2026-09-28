# Funny HW1 — Лексер: регулярные выражения → НКА → ДКА → минимизация

## 1. Структура проекта

```text
funny_hw1/
├── README.md
├── tokens.json
├── src/
│   ├── regex_engine.py
│   ├── automaton.py
│   ├── lexer.py
│   └── main.py
├── tests/
│   └── lexer_tests.json
├── output/
└── templates/
```

### Назначение файлов

- `tokens.json` — список регулярных выражений токенов Funny.
- `regex_engine.py` — собственный разбор regex, построение НКА Томпсона, subset construction и Хопкрофт.
- `automaton.py` — объединение всех token-NFA и сериализация ДКА.
- `lexer.py` — longest-match лексер и trap.
- `main.py` 
- `tests/lexer_tests.json` — обязательные положительные и отрицательные тесты.
- `output/` — сгенерированные `dfa.json`, `minimized_dfa.json`, `stats.json`.

## 2. Требования

Проверить:

```bash
python3 --version
```

Сторонние пакеты не нужны.

## 3. Сборка автомата

Из корня проекта:

```bash
python3 src/main.py build
```

После этого появятся:

```text
output/dfa.json
output/minimized_dfa.json
output/stats.json
 ```

`dfa.json` — полный ДКА после subset construction.

`minimized_dfa.json` — минимизированный ДКА после алгоритма Хопкрофта.

`stats.json` содержит размеры НКА/ДКА до и после минимизации.

## 4. Запуск тестов

```bash
python3 src/main.py test
```

При успехе:
```text
[PASS] ...
...
34/34 tests passed.
``` 

Тесты покрывают:

- пустую строку;
- пробелы, табы;
- `0`;
- `01` как отрицательный пример одного INT-токена;
- идентификаторы;
- идентификаторы с `_` как ошибку;
- ключевые слова `function`, `returns`, `while`, `if`, `else`,
  `assert`, `assume`, `invariant`, `length`;
- `()[]{},;`;
- `+ - * /`;
- `== != <= >= < > =`;
- комментарии `//...`;
- longest match (`function1` → `IDENT`);
- ASCII trap;
- non-ASCII trap;
- смешанный пример Funny-кода.

## 5. Проверка одного токена

Например:

```bash
python3 src/main.py token function
```

Результат:

FUNCTION

```bash
python3 src/main.py token 123
```

Результат:

INT

```bash
python3 src/main.py token 01
```

Результат:

REJECT

Проверка идентификатора:

```bash
python3 src/main.py token abc123
```

Результат:

IDENT

Проверка `_abc`:

```bash
python3 src/main.py token _abc
```

Результат:

REJECT

## 6. Запуск настоящего сканирования

```bash
python3 src/main.py scan "function f(a:int) returns x:int { x = a + 1; }"
```

Получится примерно:

```text
FUNCTION     'function' [0:8]
IDENT        'f' [9:10]
LPAREN       '(' [10:11]
IDENT        'a' [11:12]
COLON        ':' [12:13]
INT_TYPE     'int' [13:16]
RPAREN       ')' [16:17]
RETURNS      'returns' [18:25]
IDENT        'x' [26:27]
COLON        ':' [27:28]
INT_TYPE     'int' [28:31]
LBRACE       '{' [32:33]
IDENT        'x' [34:35]
ASSIGN       '=' [36:37]
IDENT        'a' [38:39]
PLUS         '+' [40:41]
INT          '1' [42:43]
SEMICOLON    ';' [43:44]
RBRACE       '}' [45:46]
```

WS и COMMENT распознаются ДКА, но не попадают в итоговый список токенов, потому что у них `skip=true`.

## 7. Какие регулярные выражения используются

### Пробелы

[ \t\r\n]+

### Комментарий

//[^\r\n]*

### Идентификатор

По условию Funny:

[A-Za-z][A-Za-z0-9]*

Поэтому `_abc` не является IDENT.

### Целое число

0|[1-9][0-9]*

Поэтому:

0       — корректно
123     — корректно
01      — не является одним INT-токеном

### Ключевые слова

Например:

function
returns
while
if
else
assert
assume
invariant
length

Их отдельные regex нужны потому, что `function` одновременно подходит под `IDENT`.

## 8. Приоритет токенов

Для двух принимающих состояний используется приоритет из `tokens.json`: меньший индекс = больший приоритет

Ключевые слова стоят раньше `IDENT`.

Но сначала применяется правило longest match.

Поэтому:

function

получает `FUNCTION`, а

function1

получает `IDENT`.

Это важное поведение лексера.

## 9. Как построен автомат

Для каждого regex:

regex
  ↓
AST регулярного выражения
  ↓
НКА Томпсона

Затем все НКА объединяются одним новым стартовым состоянием:

                 → NFA(function)
common start →  → NFA(IDENT)
                 → NFA(INT)
                 → ...

После этого:

объединённый НКА
       ↓
epsilon-closure
       ↓
subset construction
       ↓
ДКА
       ↓
Hopcroft
       ↓
минимизированный ДКА

Алфавит фиксирован как ASCII: 128 символов.

ДКА полный: для отсутствующего перехода используется trap-state.

## 10. Почему trap нужен

Если из текущего состояния нет перехода по символу, автомат переходит в trap. Trap имеет переходы сам в себя по всем ASCII-символам.

Это позволяет иметь полную таблицу переходов:

state × 128 symbols

и отдельно проверять символы вне ASCII.

Например:

é не входит в алфавит и сразу считается ошибкой.

## 11. Момент про `01`

В HW1 01 задан как отрицательный пример.

В проекте есть специальный тест:

token("01") → REJECT

Это проверяет именно распознавание всей строки как одного INT-токена.

При полноценном сканировании исходной программы стандартный longest-match лексер может рассматривать `01` как два токена:

INT("0")
INT("1")

## 12. Формат сериализованного ДКА

`output/minimized_dfa.json` содержит:

```json
{
  "alphabet": "ASCII",
  "alphabet_size": 128,
  "start_state": 0,
  "trap_state": 1,
  "state_count": 42,
  "accepting": {
    "5": {
      "token": "IDENT",
      "priority": 22,
      "skip": false
    }
  },
  "symbols": [...],
  "transitions": [...]
}
```

Таким образом, таблицу можно непосредственно использовать в будущем T0-лексере.

## 13. Воспроизводимость

```bash
python3 src/main.py build
python3 src/main.py test
```

Достаточно для воспроизведения результата.

