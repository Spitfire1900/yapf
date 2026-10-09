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
"""Exercise yapf-diff with real formatter subprocesses and newer syntax."""

import difflib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yapf
from yapf.yapflib import yapf_api

try:
  from yapf_third_party.yapf_diff import yapf_diff
except ModuleNotFoundError as exc:
  if exc.name != 'yapf_third_party':
    raise
  # The source checkout maps this directory at package-build time.
  from third_party.yapf_third_party.yapf_diff import yapf_diff

FEATURE_SOURCES = {
    'pep695': 'class Box[T:int](Base[T]):\n pass\n',
    'pep696': 'type Callback[T=int,**P=[str]]=Callable[P,T]\n',
    'pep701': 'message=f"{data["key"]}"\n',
    'pep750': 'message=t"{ data["key"]  = !r}"\n',
    'pep758': 'try:\n work()\nexcept* A,B,C:\n recover()\n',
    'pep798': 'result=tuple(*items for items in groups)\n',
    'pep810': 'lazy from package import first,second\n',
}


def InputDiff(name, before, after):
  return ''.join(
      difflib.unified_diff(
          before.splitlines(keepends=True),
          after.splitlines(keepends=True),
          fromfile='a/' + name,
          tofile='b/' + name,
          n=0))


def OutputDiff(name, before, after):
  return ''.join(
      difflib.unified_diff(
          before.splitlines(keepends=True), after.splitlines(keepends=True),
          name, name, '(before formatting)', '(after formatting)'))


class YapfDiffSyntaxTest(unittest.TestCase):

  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name)
    self.original_cwd = Path.cwd()
    self.addCleanup(os.chdir, self.original_cwd)
    os.chdir(self.root)
    self.real_popen = subprocess.Popen

  def runDiff(self, diff, in_place=False):
    output = io.StringIO()
    argv = ['yapf-diff', '-p1', '--style', 'pep8', '--binary', 'test-yapf']
    if in_place:
      argv.append('-i')

    def launch(command, **kwargs):
      self.assertEqual(command[0], 'test-yapf')
      env = os.environ.copy()
      root = str(Path(yapf.__file__).resolve().parent.parent)
      env['PYTHONPATH'] = os.pathsep.join(
          filter(None, (root, env.get('PYTHONPATH', ''))))
      env['PYTHONIOENCODING'] = 'utf-8'
      # Only route the executable to this checkout/interpreter. The formatter
      # runs in a real child process; parsing/formatting/I/O are not mocked.
      return self.real_popen(
          [sys.executable, '-m', 'yapf'] + command[1:], env=env, **kwargs)

    with mock.patch.object(sys, 'argv', argv), \
         mock.patch.object(sys, 'stdin', io.StringIO(diff)), \
         mock.patch.object(sys, 'stdout', output), \
         mock.patch.object(yapf_diff.subprocess, 'Popen', side_effect=launch):
      yapf_diff.main()
    return output.getvalue()

  def testEachPepPreviewAndInPlace(self):
    for name, source in FEATURE_SOURCES.items():
      filename = name + '.py'
      path = self.root / filename
      path.write_text(source, encoding='utf-8')
      diff = InputDiff(filename, '', source)
      expected, _ = yapf_api.FormatCode(source, style_config='pep8')
      with self.subTest(pep=name):
        self.assertEqual(
            OutputDiff(filename, source, expected), self.runDiff(diff))
        self.assertEqual(source, path.read_text(encoding='utf-8'))
        self.assertEqual('', self.runDiff(diff, in_place=True))
        self.assertEqual(expected, path.read_text(encoding='utf-8'))

  def testChangedInteriorStringLineSelectsItsStatement(self):
    for kind in ('f', 't'):
      source = 'before=1\nresult=' + kind + '"{\n value+2\n}"\nafter=2\n'
      before = source.replace('value+2', 'value+1')
      expected = source.replace('result=', 'result = ')
      path = self.root / 'literal.py'
      path.write_text(source, encoding='utf-8')
      diff = InputDiff('literal.py', before, source)
      with self.subTest(kind=kind):
        self.assertEqual(
            OutputDiff('literal.py', source, expected), self.runDiff(diff))
        self.runDiff(diff, in_place=True)
        self.assertEqual(expected, path.read_text(encoding='utf-8'))

  def testChangedLineAfterStringDoesNotSelectString(self):
    source = 'result=t"{\n value+2\n}"\nafter=2\n'
    before = source.replace('after=2', 'after=1')
    path = self.root / 'after.py'
    path.write_text(source, encoding='utf-8')
    self.runDiff(InputDiff('after.py', before, source), in_place=True)
    self.assertEqual(
        source.replace('after=2', 'after = 2'),
        path.read_text(encoding='utf-8'))

  def testMultipleNewSyntaxFiles(self):
    diff = ''
    for name, source in FEATURE_SOURCES.items():
      filename = name + '.py'
      (self.root / filename).write_text(source, encoding='utf-8')
      diff += InputDiff(filename, '', source)
    self.runDiff(diff, in_place=True)
    for name, source in FEATURE_SOURCES.items():
      with self.subTest(pep=name):
        self.assertEqual(
            yapf_api.FormatCode(source, style_config='pep8')[0],
            (self.root / (name + '.py')).read_text(encoding='utf-8'))

  def testCrLfBomAndInteriorRange(self):
    source = 'before=1\r\nresult=t"{\r\n value+2\r\n}"\r\nafter=2\r\n'
    path = self.root / 'encoded.py'
    path.write_bytes(source.encode('utf-8-sig'))
    self.runDiff(
        InputDiff('encoded.py', source.replace('value+2', 'value+1'), source),
        in_place=True)
    self.assertEqual(
        source.replace('result=', 'result = ').encode('utf-8-sig'),
        path.read_bytes())

  def testDisabledNewSyntaxIsPreserved(self):
    source = ('# yapf: disable\n'
              'type Alias[T=int]=list[T]\n'
              '# yapf: enable\nvalue=1\n')
    path = self.root / 'disabled.py'
    path.write_text(source, encoding='utf-8')
    self.runDiff(InputDiff('disabled.py', '', source), in_place=True)
    self.assertEqual(
        source.replace('value=1', 'value = 1'),
        path.read_text(encoding='utf-8'))

  def testUpstreamFailuresDoNotOverwriteFailingFile(self):
    for prefix in ('class C(metaclass=M,*bases):\n pass\n',
                   'template=t"a" t"b"\n', 'template=tr"{name}"\n',
                   'try:\n pass\nexcept A,:\n pass\n'):
      source = prefix + '\nvalue=2\n'
      path = self.root / 'unsupported.py'
      path.write_text(source, encoding='utf-8')
      diff = InputDiff('unsupported.py', source.replace('value=2', 'value=1'),
                       source)
      with self.subTest(prefix=prefix):
        with self.assertRaises(SystemExit) as context:
          self.runDiff(diff, in_place=True)
        self.assertNotEqual(0, context.exception.code)
        self.assertEqual(source, path.read_text(encoding='utf-8'))


if __name__ == '__main__':
  unittest.main()
