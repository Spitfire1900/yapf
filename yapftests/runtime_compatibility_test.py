# Copyright 2026 Google Inc. All Rights Reserved.
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
"""Configuration contracts for the Python 3.11+ runtime baseline."""

import tempfile
import tomllib
import unittest
from pathlib import Path

from yapf.yapflib import file_resources
from yapf.yapflib import style
from yapf.yapflib import yapf_api
from yapftests import yapf_test_helper


class RuntimeCompatibilityTest(yapf_test_helper.YAPFTest):

  def testTomlReadersUseStandardLibrary(self):
    self.assertIs(tomllib, style.tomllib)
    self.assertIs(tomllib, file_resources.tomllib)

  def testTomlConfigurationAndIgnoreDiscovery(self):
    with tempfile.TemporaryDirectory() as directory:
      config = Path(directory) / 'pyproject.toml'
      config.write_text(
          '[tool.yapf]\n'
          'based_on_style = "pep8"\n'
          'indent_width = 2\n'
          '[tool.yapfignore]\n'
          'ignore_patterns = ["generated/*.py", "caf\u00e9/*.py"]\n',
          encoding='utf-8')
      discovered = file_resources.GetDefaultStyleForDir(directory)
      self.assertEqual(str(config), discovered)
      self.assertEqual(['generated/*.py', 'caf\u00e9/*.py'],
                       file_resources.GetExcludePatternsForDir(directory))
      formatted, _ = yapf_api.FormatCode(
          'if True:\n    answer=42\n', style_config=discovered)
      self.assertEqual('if True:\n  answer = 42\n', formatted)

  def testMalformedTomlUsesNativeDiagnostic(self):
    with tempfile.TemporaryDirectory() as directory:
      config = Path(directory) / 'pyproject.toml'
      config.write_text('[tool.yapf\n', encoding='utf-8')
      for reader in (style.CreateStyleFromConfig,
                     file_resources._GetExcludePatternsFromPyprojectToml):
        with self.subTest(reader=reader.__name__):
          with self.assertRaises(tomllib.TOMLDecodeError):
            reader(str(config))


if __name__ == '__main__':
  unittest.main()
