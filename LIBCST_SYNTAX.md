# Modern Python syntax on the LibCST backend

## Branch and implementation boundary

`feature/libcst-python-syntax-20261009` starts at the validated LibCST migration
`6aaf2c4272e14402929ac4de07e31a11692d1186` and includes its Python 3.11+
runtime update. It does not merge, cherry-pick, or
rewrite the earlier PEP branches. Their regression scenarios are retained as
behavioral specifications, but implementation is in the new layout front end.

LibCST remains the sole Python parser. There are no additional Python grammars,
source tokenizers, contextual-keyword lookahead, AST fallback, or runtime
monkey-patches to LibCST. The existing migration's narrow, source-checked EOF
comment recovery is retained. The dependency remains `libcst>=1.9.0,<1.10`;
its private code-generation interface is still isolated in `frontend.py`.
LibCST 1.9.0 is still the latest stable release verified on 2026-10-09 and
already supports Python 3.11. The raised runtime floor removes obsolete
compatibility paths; it does not resolve the upstream parser restrictions
listed below. No source feature is disabled merely because the formatter
runs on Python 3.11. Only native CPython syntax/semantics tests retain their
feature-specific version guards.

## Supported formatting

| PEP | Constructs | Layout behavior |
| --- | --- | --- |
| [695](https://peps.python.org/pep-0695/) | `type` aliases; generic functions, async functions and classes; bounds, constraints, `*Ts`, `**P` | Dedicated declaration contexts distinguish brackets/colons from subscripts/slices; type parameters do not become function value parameters. |
| [696](https://peps.python.org/pep-0696/) | Type-variable, parameter-specification and type-variable-tuple defaults | Spaces around declaration `=`; nested expressions retain their own spacing; comments, trailing commas and wrapping are handled. |
| [701](https://peps.python.org/pep-0701/) | Quote reuse, comments, backslashes, nesting and multiline replacement fields | Source spelling remains opaque and unchanged; literal end positions and line-range selection include physical interior lines. |
| [750](https://peps.python.org/pep-0750/) | T-strings, supported raw prefixes, nested/mixed f-/t-strings | Same preservation contract as f-strings, including observable interpolation expression text. See upstream gaps below. |
| [758](https://peps.python.org/pep-0758/) | Unparenthesized exception lists, trailing commas, `except*` | Correct comma/colon and `except*` spacing. No illegal physical line breaks are introduced in unparenthesized lists. |
| [798](https://peps.python.org/pep-0798/) | List/set/dict unpacking comprehensions; starred generators, including sole call arguments; async and filtered forms | Reuses existing comprehension/call layout with unpacking roles. Parentheses and argument structure are preserved. |
| [810](https://peps.python.org/pep-0810/) | Lazy imports and from-imports, relative names, aliases, comments and import lists | Existing import formatting and import/variable blank-line policy apply; ordinary identifiers named `lazy` remain identifiers. |

Type-parameter declaration spacing is not controlled by keyword-argument
spacing: `T = int` stays a declaration even when a nested `Factory(option=True)`
uses different spacing. The existing formatter styles and search algorithm
are retained, rather than introducing a separate style engine for new syntax.

Valid Unicode identifiers, including U+2118 and combining characters, are
handled by LibCST and have explicit regression coverage. Their spelling is
preserved rather than normalized by YAPF.

## Literal and range guarantees

F-string and t-string contents are not reformatted. This includes all literal
text, replacement expressions, debug expressions, comments, whitespace and
format specifications. T-string expression source can be observed by application
code, so changing it is not generally a semantics-neutral formatting operation.

Selecting a physical line inside a multiline literal selects its containing
logical statement. The literal itself remains unchanged, and unselected
neighboring statements are not reformatted. The same behavior applies to
`FormatCode`, `FormatFile`, CLI `--lines`, and `yapf-diff`'s generated ranges.
CRLF and UTF-8 BOM preservation are covered by file-based tests.

`yapf-diff` must receive a zero-context diff (`git diff -U0`). As before, the
entire file is parsed, even when only one line is selected. A dependency error
outside selected lines still prevents formatting. A failed file is not
rewritten. Multiple-file operations are not transactional: files successfully
processed before an error can already have been changed.

## Known LibCST 1.9.0 limitations

These are reproducible directly with the supplied LibCST release, without
importing YAPF. The syntax support above is **not** a claim of complete
Python 3.15 compatibility.

| Valid source | Dependency failure | Practical supported form |
| --- | --- | --- |
| `value = tr"{name}"` (also `Tr`, `tR`, `TR`) | Native parser rejects the reversed raw-template prefix. | `rt"{name}"` and its case variants parse. |
| `value = t"a" t"b"` | `ConcatenatedString` validation raises `CSTLogicError` because its validation does not handle a right-hand `TemplatedString`. | Single t-strings and separate t-string function arguments work. |
| `except ValueError,:` (also `except*`) | Native parser rejects a singleton unparenthesized tuple. | `(ValueError,)` works; unparenthesized lists with two or more elements work. |
| `(*left if enabled else right for left in groups)` (also sole generator call arguments and dictionary unpacking comprehensions) | Native parser rejects a full unparenthesized conditional unpacking expression. | Parenthesize the conditional: `(*(left if enabled else right) for left in groups)`. |
| `class C(metaclass=M, *bases): pass` | `ClassDef` cannot preserve interleaving of bases and keywords. | This existing migration limitation remains; YAPF does not rearrange the header. |

The singleton-exception case follows the Python 3.14 `expressions` grammar;
the conditional-generator and dictionary cases follow Python 3.15's full
`expression` rules. These are dependency restrictions, not assertions that the
source is invalid Python. Regression tests construct valid public CST nodes
for the first, third, and fourth cases and verify `FormatTree` can format
them: those layout rules are ready when upstream parsing is fixed. That does
not make the same text usable with `FormatCode` or the CLI today.

YAPF now converts `CSTLogicError` during parsing into its normal filename-based
error boundary with an explicit LibCST representation diagnostic. It does not
silently mutate literals, bypass LibCST node validation, patch global classes,
or substitute another parser. An upstream fix and revalidation are required
for complete support of the affected PEPs.

Long unparenthesized exception lists may exceed the column limit instead of
introducing invalid continuation syntax. Adding/removing their parentheses as
a style transformation is outside this change.

A formatter is not a substitute for Python's compiler or symbol-table checks.
For example, accepting a `lazy import` node does not certify that it appears
in a scope permitted by Python, nor does formatting a type bound prove it is
a valid typing expression.

## Verification

```bash
python -m pip install .
python -m unittest discover -p '*_test.py' yapftests/
python -m pytest -q
```

The new PEP tests keep newer syntax in string fixtures so the suite itself
runs on the formatter's Python 3.11+ runtime. AST comparisons and executable
semantics tests run only on interpreters that implement the feature. Native
checks include type-parameter defaults, f-string debug output, template
metadata, exception handlers, unpacking semantics and lazy-import AST flags.

Tests also cover mixed-feature modules across styles and column limits,
input-CST immutability, contextual identifiers, source coordinates, selected
ranges, disabled regions, and real formatter subprocesses invoked by
`yapf-diff`. Known dependency restrictions have separately named tests; a
passing restriction test is not successful formatting of that input.

CI/tox include Python 3.11 through 3.15. This is configuration, not evidence
that every environment has run. Executed interpreter/platform combinations,
full source/wheel/archive results, differential comparisons, and independent
command-line checks belong in the accompanying delivery validation report.
