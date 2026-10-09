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
"""Regression coverage for PEP 798, including exact output and stability."""

import ast
import sys
import unittest

import libcst as cst

from yapf.yapflib import errors
from yapf.yapflib.yapf_api import FormatCode
from yapf.yapflib.yapf_api import FormatTree


class Pep798Test(unittest.TestCase):

  def assertFormatting(self, source, expected=None, style='pep8'):
    result, _ = FormatCode(source, style_config=style)
    if expected is not None:
      self.assertEqual(expected, result)
    again, changed = FormatCode(result, style_config=style)
    self.assertEqual(result, again)
    self.assertFalse(changed)
    if sys.version_info >= (3, 15):
      self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))
    return result

  def testAllComprehensionKinds(self):
    cases = [
        ('flat=[* items for items in groups]\n',
         'flat = [*items for items in groups]\n'),
        ('flat={* items for items in groups}\n',
         'flat = {*items for items in groups}\n'),
        ('merged={** mapping for mapping in mappings}\n',
         'merged = {**mapping for mapping in mappings}\n'),
        ('flat=(* items for items in groups)\n',
         'flat = (*items for items in groups)\n'),
        ('flat=tuple(* items for items in groups)\n',
         'flat = tuple(*items for items in groups)\n'),
        ('flat=tuple((* items for items in groups))\n',
         'flat = tuple((*items for items in groups))\n'),
    ]
    for source, expected in cases:
      with self.subTest(source=source):
        self.assertFormatting(source, expected)

  def testFullExpressionsInGeneratorAndMappingHeads(self):
    sources = [
        'flat=(*(left if enabled else right) for left in groups)\n',
        'flat=tuple(*(left if enabled else right) for left in groups)\n',
        'merged={**(left if enabled else right) for left in mappings}\n',
        'flat=tuple(*(chosen:=items) for items in groups)\n',
        'flat=tuple(*factory(items) for items in groups if items)\n',
        'flat=tuple(*obj.items[1:] for obj in groups)\n',
    ]
    for source in sources:
      with self.subTest(source=source):
        self.assertFormatting(source)

  def testUpstreamUnparenthesizedConditionalRestriction(self):
    # PEP 798/CPython 3.15 allow a full expression in generator and mapping
    # heads. LibCST 1.9.0 instead requires parentheses around a conditional.
    for expression in (
        '(*left if enabled else right for left in groups)',
        'tuple(*left if enabled else right for left in groups)',
        '{**left if enabled else right for left in groups}',
    ):
      source = 'flat=' + expression + '\n'
      with self.subTest(source=source):
        with self.assertRaises(cst.ParserSyntaxError):
          cst.parse_module(source)
        with self.assertRaises(errors.YapfError):
          FormatCode(source)
        parenthesized = source.replace('left if enabled else right',
                                       '(left if enabled else right)')
        module = cst.parse_module(parenthesized)
        expression_node = module.body[0].body[0].value
        if isinstance(expression_node, cst.Call):
          expression_node = expression_node.args[0].value
        conditional = (
            expression_node.elt.value if isinstance(
                expression_node, cst.GeneratorExp) else expression_node.value)
        module = module.deep_replace(conditional,
                                     conditional.with_changes(lpar=(), rpar=()))
        self.assertEqual(source, module.code)
        self.assertEqual('flat = ' + expression + '\n',
                         FormatTree(module, style_config='pep8'))

  def testAsyncComprehensions(self):
    for expression in ('[*items async for items in groups]',
                       '{*items async for items in groups}',
                       '{**items async for items in groups}',
                       '(*items async for items in groups)',
                       'tuple(*items async for items in groups)',
                       'tuple(*(await fetch(x)) async for x in groups)'):
      source = 'async def flatten(groups):\n return ' + expression + '\n'
      with self.subTest(expression=expression):
        self.assertFormatting(source)

  def testNestedClausesAndComments(self):
    sources = [
        'flat=tuple(*items for group in groups for items in group if items)\n',
        'flat=tuple(\n *items # retained\n for items in groups if items\n)\n',
        'merged={\n **items # retained\n for items in mappings\n}\n',
        'flat=[*items for items in groups if items if enabled]\n',
    ]
    for source in sources:
      for name in ('pep8', 'google', 'yapf', 'facebook'):
        for limit in (30, 50, 88):
          with self.subTest(source=source, style=name, limit=limit):
            result = self.assertFormatting(
                source,
                style={
                    'BASED_ON_STYLE': name,
                    'COLUMN_LIMIT': limit,
                    'DEDENT_CLOSING_BRACKETS': True
                })
            if '# retained' in source:
              self.assertIn('# retained', result)

  def testExistingUnpackingAndLoopTargets(self):
    sources = [
        'call(*args,**kwargs)\n',
        'value=(*left,*right)\n',
        'value={**left,**right}\n',
        'value=[*left,*right]\n',
        'for *head,tail in items:\n pass\n',
        'head,*tail=items\n',
        'value=call(x for x in values)\n',
        'value=items[*indices]\n',
    ]
    for source in sources:
      with self.subTest(source=source):
        result = self.assertFormatting(source)
        if sys.version_info >= (3, 11):
          self.assertEqual(
              ast.dump(ast.parse(source)), ast.dump(ast.parse(result)))

  @unittest.skipUnless(sys.version_info >= (3, 15), 'requires Python 3.15')
  def testNativeUnpackingSemantics(self):
    source = ('groups=[[1,2],[3]]\n'
              'flat=[*items for items in groups]\n'
              'unique={*items for items in groups}\n'
              'generated=tuple(*items for items in groups)\n'
              'merged={**mapping for mapping in [{"x":1},{"x":2,"y":3}]}\n')
    namespace = {}
    exec(self.assertFormatting(source), namespace)
    self.assertEqual([1, 2, 3], namespace['flat'])
    self.assertEqual({1, 2, 3}, namespace['unique'])
    self.assertEqual((1, 2, 3), namespace['generated'])
    self.assertEqual({'x': 2, 'y': 3}, namespace['merged'])


if __name__ == '__main__':
  unittest.main()
