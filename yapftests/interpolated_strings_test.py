# Copyright 2026 The YAPF Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""PEP 701/750: literal preservation, emission positions and range formatting."""

import ast
import itertools
import sys
import tempfile
import unittest
from pathlib import Path

import libcst as cst

from yapf.layout import frontend
from yapf.layout import tokens
from yapf.yapflib import errors
from yapf.yapflib import yapf_api
from yapftests import yapf_test_helper

FSTRINGS = (
    'f"{data["key"]}"',
    "f'{data['key']}'",
    'f"{f"{f"{value}"}"}"',
    'f"{"\\n".join(items)}"',
    'f"{value # quotes " and } are part of this comment\n}"',
    'f"{value + \\\nother}"',
    'f"{value\n}"',
    'f"{value  =  !r}"',
    'f"{value:{width # ignored }\n}.{precision}f}"',
    'f"""{data["""key"""]}"""',
    'rf"{{literal}} {data["key"]}"',
    'f"\\N{LEFT CURLY BRACKET}{value}"',
)
TSTRINGS = tuple(literal.replace('f', 't', 1) for literal in FSTRINGS) + (
    't"{t"{value}"}"',
    't"{f"{t"{data["key"]}"}"}"',
    'f"{t"{f"{data["key"]}"}"}"',
    'rt"\\N{value}"',
)


def LiteralValues(source):
  return [
      leaf.value
      for leaf in frontend.ParseCode(source).leaves()
      if leaf.type == tokens.STRING
  ]


class InterpolatedStringsTest(unittest.TestCase):

  def assertFormatting(self, source, expected=None, version=(3, 12), **kwargs):
    kwargs.setdefault('style_config', 'pep8')
    result, _ = yapf_api.FormatCode(source, **kwargs)
    if expected is not None:
      self.assertEqual(expected, result)
    self.assertEqual(LiteralValues(source), LiteralValues(result))
    self.assertEqual((result, False), yapf_api.FormatCode(result, **kwargs))
    if sys.version_info >= version:
      self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
      compile(result, '<formatted>', 'exec')
    return result

  def testPep701SourceIsPreserved(self):
    for literal in FSTRINGS:
      with self.subTest(literal=literal):
        self.assertFormatting('result=' + literal + '\n',
                              'result = ' + literal + '\n')

  def testPep750SourceAndMixedNestingArePreserved(self):
    for literal in TSTRINGS:
      for name in ('pep8', 'google', 'yapf', 'facebook'):
        with self.subTest(literal=literal, style=name):
          self.assertFormatting(
              'result=' + literal + '\n',
              'result = ' + literal + '\n',
              version=(3, 14),
              style_config=name)

  def testPrefixQuoteBodyMatrix(self):
    for kind in ('f', 't'):
      prefixes = (kind, kind.upper(), 'r' + kind, 'r' + kind.upper(),
                  'R' + kind, 'R' + kind.upper())
      if kind == 'f':
        prefixes += ('fr', 'Fr', 'fR', 'FR')
      for prefix, quote, body in itertools.product(
          prefixes, ('"', "'", '"""', "'''"),
          ('', 'literal', '{{escaped}}', '{name}', '{name=}',
           '{name  =  !r:>{width}}', '{ {1:2} }')):
        literal = prefix + quote + body + quote
        with self.subTest(literal=literal):
          self.assertFormatting(
              'value=' + literal + '\n',
              'value = ' + literal + '\n',
              version=(3, 14) if kind == 't' else (3, 12))

  def testConcatenationAndExpressionStatements(self):
    for kind in ('f', 't'):
      for source in (
          'value={k}"hello" {k}"{{name}}"\n',
          'value=({k}"first"\n # comment\n r{k}"second {{name}}")\n',
          '{k}"{{value}}"\nother=1\n',
          'process({k}"{{a}}",{k}"{{b}}")\n',
      ):
        if kind == 't' and source.startswith('value='):
          # Adjacent t-strings hit a LibCST 1.9.0 validation bug, covered below.
          continue
        with self.subTest(kind=kind, source=source):
          self.assertFormatting(source.format(k=kind), version=(3, 14))

  def testUpstreamReversedRawTemplatePrefixRestriction(self):
    for prefix in ('tr', 'Tr', 'tR', 'TR'):
      for quote in ('"', "'", '"""', "'" * 3):
        with self.subTest(prefix=prefix, quote=quote):
          module = cst.parse_module('value=rt' + quote + '{name}' + quote +
                                    '\n')
          literal = module.body[0].body[0].value
          module = module.deep_replace(
              literal, literal.with_changes(start=prefix + quote))
          # The adapter already supports the node. The native parser does not.
          with self.assertRaises(cst.ParserSyntaxError):
            cst.parse_module(module.code)
          with self.assertRaises(errors.YapfError):
            yapf_api.FormatCode(module.code)
          self.assertEqual(
              module.code.replace('value=', 'value = '),
              yapf_api.FormatTree(module))

  def testUpstreamTemplateConcatenationRestriction(self):
    for source in ('value=t"first" t"second {name}"\n',
                   'value=(t"first"\n # comment\n rt"second {name}")\n',
                   'value=t"a" t"b" t"c"\n'):
      with self.subTest(source=source):
        with self.assertRaises(cst.CSTLogicError):
          cst.parse_module(source)
        with self.assertRaisesRegex(errors.YapfError,
                                    'LibCST could not represent this source'):
          yapf_api.FormatCode(source, filename='template.py')

  def testMultilineLiteralThenCode(self):
    for kind in ('f', 't'):
      for source in (
          'result={k}"{{value # field\n}}";other=1\n',
          'result=[{k}"{{value # field\n}}",{k}"{{data["key"]}}"]\n'
          'following=2\n',
          'result={k}"{{value # field\n}}" # trailing\nother=1\n',
          'def f():\n return {k}"{{value # field\n}}"\nother=1\n',
      ):
        with self.subTest(kind=kind, source=source):
          self.assertFormatting(source.format(k=kind), version=(3, 14))

  def testSourcePositionsAndLogicalLineEnd(self):
    for kind, newline in itertools.product(('f', 't'), ('\n', '\r\n')):
      literal = kind + '"{value # field' + newline + '}"'
      source = 'result = ' + literal + '; after = 1' + newline
      leaves = list(frontend.ParseCode(source).leaves())
      string = next(leaf for leaf in leaves if leaf.type == tokens.STRING)
      semicolon = next(leaf for leaf in leaves if leaf.value == ';')
      after = next(leaf for leaf in leaves if leaf.value == 'after')
      with self.subTest(kind=kind, newline=newline):
        self.assertEqual(literal, string.value)
        self.assertEqual((1, 9), (string.lineno, string.column))
        self.assertEqual((2, 2), (semicolon.lineno, semicolon.column))
        self.assertEqual((2, 4), (after.lineno, after.column))
        line = yapf_test_helper.ParseAndUnwrap('result = ' + literal +
                                               newline)[0]
        self.assertEqual((2, 2), line.end)
        self.assertTrue(line.last.is_multiline_string)

  def testInteriorLineSelection(self):
    literals = ('f"{value # field\n}"', 't"{value # field\n}"',
                'f"""value={value}\n"""', 't"""value={value}\n"""',
                '"""line\ncontinued"""', "'line\\\ncontinued'")
    for literal in literals:
      source = 'before=1\nresult=' + literal + '\nafter=2\n'
      expected = 'before=1\nresult = ' + literal + '\nafter=2\n'
      for selected in (2, 3):
        with self.subTest(literal=literal, selected=selected):
          self.assertFormatting(
              source, expected, version=(3, 14), lines=[(selected, selected)])

  def testRangeDoesNotSelectFollowingStatement(self):
    for kind in ('f', 't'):
      literal = kind + '"{value # field\n}"'
      source = 'result=' + literal + '\nother=1\n'
      self.assertFormatting(
          source,
          'result=' + literal + '\nother = 1\n',
          version=(3, 14),
          lines=[(3, 3)])

  def testDisabledMultilineLiteral(self):
    for kind in ('f', 't'):
      source = ('# yapf: disable\nresult=' + kind + '"{value # field\n}";x=1\n'
                '# yapf: enable\nother=2\n')
      self.assertFormatting(
          source, source.replace('other=2', 'other = 2'), version=(3, 14))

  def testCrLfBomFileRoundTrip(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / 'literal.py'
      source = 'before=1\r\nresult=t"{value # field\r\n}"\r\nafter=2\r\n'
      path.write_bytes(source.encode('utf-8-sig'))
      yapf_api.FormatFile(str(path), lines=[(3, 3)], in_place=True)
      self.assertEqual(
          source.replace('result=', 'result = ').encode('utf-8-sig'),
          path.read_bytes())

  def testPrefixNamesRemainIdentifiers(self):
    self.assertFormatting(
        't=1\nT=2\nrt=3\ntr=4\nresult=t+T+rt+tr\n',
        't = 1\nT = 2\nrt = 3\ntr = 4\n'
        'result = t + T + rt + tr\n')

  def testMalformedLiteralsAreRejected(self):
    for kind, suffix in itertools.product(
        ('f', 't'), ('"{value', '"{(value]}"', '"}"', '"{x # missing end',
                     '"line\nbreak"')):
      with self.subTest(kind=kind, suffix=suffix):
        with self.assertRaises(errors.YapfError):
          yapf_api.FormatCode('value=' + kind + suffix + '\n')
    for prefix in ('ft', 'tf', 'bt', 'tb', 'ut', 'tu', 'rrt', 'trr'):
      with self.subTest(prefix=prefix):
        with self.assertRaises(errors.YapfError):
          yapf_api.FormatCode('value=' + prefix + '"text"\n')

  @unittest.skipUnless(sys.version_info >= (3, 12), 'requires Python 3.12')
  def testNativeFStringDebugText(self):
    source = 'value=5\nmessage=f"{ value + 1   = !r:>{2+1}}"\n'
    before, after = {}, {}
    exec(source, before)
    exec(self.assertFormatting(source), after)
    self.assertEqual(before['message'], after['message'])

  @unittest.skipUnless(sys.version_info >= (3, 14), 'requires Python 3.14')
  def testNativeTemplateMetadata(self):
    source = 'value=5\nmessage=t"{ value + 1   = !r:>{2+1}}"\n'
    before, after = {}, {}
    exec(source, before)
    exec(self.assertFormatting(source, version=(3, 14)), after)
    left, right = before['message'], after['message']
    self.assertEqual(left.strings, right.strings)
    self.assertEqual(len(left.interpolations), len(right.interpolations))
    for a, b in zip(left.interpolations, right.interpolations):
      for attribute in ('value', 'expression', 'conversion', 'format_spec'):
        self.assertEqual(getattr(a, attribute), getattr(b, attribute))


if __name__ == '__main__':
  unittest.main()
