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
"""Cross-feature contracts for the LibCST-backed syntax extensions."""

import ast
import itertools
import sys
import unittest

import libcst as cst

from yapf.layout import frontend
from yapf.layout import tokens
from yapf.yapflib import yapf_api
from yapftests import yapf_test_helper

MIXED_SOURCE = '''lazy from collections.abc import Callable,Iterable

type Callback[T=int,**P=[str]]=Callable[P,T]

class Box[T:int=int,*Ts=*tuple[str,...]](Base[T]):
 @decorate(option=True)
 async def flatten[U=T](self,items:Iterable[U],/,*,fallback:U=None)->U:
  message=f"{items[0]["name"]}"
  template=t"{ message  =  !r}"
  flattened=[*group async for group in items if group]
  merged={**mapping for mapping in mappings}
  collected=tuple(*group for group in flattened)
  try:
   return collected
  except ValueError,TypeError,RuntimeError:
   return fallback
'''

IGNORED_TOKENS = (tokens.INDENT, tokens.DEDENT, tokens.NEWLINE,
                  tokens.ENDMARKER, tokens.COMMENT)


def SignificantTokens(source):
  return [(leaf.type, leaf.value)
          for leaf in frontend.ParseCode(source).leaves()
          if leaf.type not in IGNORED_TOKENS]


class SyntaxIntegrationTest(unittest.TestCase):

  def assertFormatting(self, source, config='pep8', native=(3, 15)):
    result, _ = yapf_api.FormatCode(source, style_config=config)
    self.assertEqual(SignificantTokens(source), SignificantTokens(result))
    self.assertEqual((result, False),
                     yapf_api.FormatCode(result, style_config=config))
    if sys.version_info >= native:
      self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
      compile(result, '<formatted>', 'exec')
    return result

  def testAllSevenFeaturesInOneModule(self):
    for name, limit, dedent in itertools.product(
        ('pep8', 'google', 'yapf', 'facebook'), (32, 50, 88), (False, True)):
      with self.subTest(style=name, limit=limit, dedent=dedent):
        self.assertFormatting(
            MIXED_SOURCE, {
                'BASED_ON_STYLE': name,
                'COLUMN_LIMIT': limit,
                'DEDENT_CLOSING_BRACKETS': dedent,
            })

  def testNativeTypeDefaultsAndNewFStringsTogether(self):
    source = ('type Alias[T:(int,str)=str]=list[T]\n'
              'class Box[T=int]:\n'
              ' def render[U=str](self,data:dict[str,U])->str:\n'
              '  return f"{data["name"]}"\n')
    for name in ('pep8', 'google', 'yapf', 'facebook'):
      with self.subTest(style=name):
        self.assertFormatting(source, name, native=(3, 13))

  def testConstructedModulesRemainImmutable(self):
    module = cst.parse_module(MIXED_SOURCE)
    original = module.code
    result = yapf_api.FormatTree(module)
    self.assertEqual(original, module.code)
    self.assertEqual(result, yapf_api.FormatTree(module))
    self.assertEqual(SignificantTokens(original), SignificantTokens(result))

  def testNestedContextualNames(self):
    for name in ('type', 'lazy', 'match', 'case'):
      source = ('{n}=type(value)\n'
                'match ({n}(value),type):\n'
                ' case (first,second):\n'
                '  type Alias[{n}=int]=tuple[{n},int]\n'
                '  result={n}\n').format(n=name)
      with self.subTest(name=name):
        self.assertFormatting(source, native=(3, 13))

  def testNestedParameterSyntaxKeepsCorrectClassification(self):
    source = ('def process[T=Factory(option=True),**P=[int,str]]('
              'value:T=Factory(option=True),/,*args:P.args,flag:bool=True,'
              '**kwargs:P.kwargs)->T:\n return value\n')
    for named_spaces, power_spaces in itertools.product((False, True),
                                                        repeat=2):
      config = {
          'SPACES_AROUND_DEFAULT_OR_NAMED_ASSIGN': named_spaces,
          'SPACES_AROUND_POWER_OPERATOR': power_spaces,
          'COLUMN_LIMIT': 55
      }
      with self.subTest(config=config):
        result = self.assertFormatting(source, config, native=(3, 13))
        self.assertIn('T = Factory(', result)
        self.assertIn('**P = [int, str]', result)
        self.assertIn('**kwargs: P.kwargs', result)

  def testSourceLocationsAfterUnicodeAndMultilineStrings(self):
    source = ('\u2118=1\na\u0301=2\n'
              'type Alias[\u03a4=int]=list[\u03a4]\n'
              'result=t"{\u2118 # comment\n}";following=\u2118\n')
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
      offsets.append(offsets[-1] + len(line))
    for leaf in frontend.ParseCode(source).leaves():
      if leaf.type in IGNORED_TOKENS:
        continue
      position = offsets[leaf.lineno - 1] + leaf.column
      with self.subTest(value=leaf.value, line=leaf.lineno, column=leaf.column):
        self.assertEqual(leaf.value,
                         source[position:position + len(leaf.value)])
    # Semicolon splitting is an existing formatter policy; the source-position
    # assertions above deliberately exercise it, independently of token parity.
    self.assertFormatting(source.replace(';', '\n'))

  def testUnicodeIdentifiersIncludingCombiningCharacters(self):
    for name in ('\u2118', 'a\u0301', '\u0394', '\u53d8\u91cf'):
      source = ('{n}=1\nresult={n}+1\n'
                'type Alias[{n}=int]=list[{n}]\n').format(n=name)
      with self.subTest(name=name):
        self.assertFormatting(source, native=(3, 13))

  def testSelectedTypeParameterLineFormatsOnlyContainingHeader(self):
    source = ('before=1\n'
              'def identity[\n T:int=int, # bound\n]('
              'value:T)->T:\n return value\nafter=2\n')
    result, _ = yapf_api.FormatCode(source, lines=[(3, 3)])
    self.assertTrue(result.startswith('before=1\n'))
    self.assertTrue(result.endswith(' return value\nafter=2\n'))
    self.assertIn('T: int = int', result)
    self.assertEqual(SignificantTokens(source), SignificantTokens(result))
    self.assertEqual((result, False),
                     yapf_api.FormatCode(result, lines=[(3, 3)]))

  def testDisabledGenericDeclaration(self):
    source = ('# yapf: disable\n'
              'type Alias[T:int=int,**P=[int,str]]=Callable[P,T]\n'
              '# yapf: enable\nother=2\n')
    result = self.assertFormatting(source, native=(3, 13))
    self.assertEqual(source.replace('other=2', 'other = 2'), result)

  def testFunctionParameterMetadataSkipsTypeParameterBracket(self):
    line = yapf_test_helper.ParseAndUnwrap(
        'def f[T=int,**P=[str]](value:T,**kwargs:P.kwargs):\n pass\n')[0]
    name = next(token for token in line.tokens if token.value == 'f')
    self.assertEqual('[', name.next_token.value)
    opening = name.next_token.matching_bracket.next_token
    self.assertEqual('(', opening.value)
    self.assertEqual(')', opening.matching_bracket.value)


if __name__ == '__main__':
  unittest.main()
