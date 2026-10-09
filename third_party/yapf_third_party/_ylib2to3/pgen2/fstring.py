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
"""Read a complete f-string without changing its source representation.

PEP 701 permits the enclosing quote, comments and newlines in replacement
fields. A regular expression for an ordinary string cannot find the end of
such an f-string. This scanner follows the lexical contexts instead, retaining
YAPF's representation of an entire string literal as a single STRING token.
It deliberately does not parse or reformat replacement expressions.
"""

import re

# Put triple quotes before single quotes, and two-letter prefixes before
# one-letter prefixes. Identifiers are consumed separately in expressions so
# that a suffix of an identifier cannot be mistaken for a string prefix.
STRING_START = re.compile(r'''(?i:(fr|rf|br|rb|r|u|b|f)?)("""|\'\'\'|"|\')''')
FSTRING_START = r'''(?:[fF][rR]?|[rR][fF])(?:"""|\'\'\'|"|\')'''
_NAME = re.compile(r'\w+')
_CLOSING = {'(': ')', '[': ']', '{': '}'}


class FStringError(Exception):
  """A lexical error, with the same arguments as tokenize.TokenError."""


def scan_fstring(readline, line, lineno, column):
  """Return (value, end_position, last_line, physical_lines) for an f-string.

  ``line`` is the physical line already read by the caller. Only subsequent
  physical lines belonging to this literal are read from ``readline``. The
  caller resumes tokenization at ``end_position`` in ``last_line``.
  """
  scanner = _Scanner(readline, line, lineno, column)
  scanner.scan_string()
  physical_lines = ''.join(scanner.lines)
  if len(scanner.lines) == 1:
    value = line[column:scanner.column]
  else:
    value = (
        line[column:] + ''.join(scanner.lines[1:-1]) +
        scanner.line[:scanner.column])
  return value, (scanner.lineno, scanner.column), scanner.line, physical_lines


class _Scanner:

  def __init__(self, readline, line, lineno, column):
    self.readline = readline
    self.line = line
    self.lineno = lineno
    self.column = column
    self.start = (lineno, column)
    self.lines = [line]

  def error(self, message):
    raise FStringError(message, self.start)

  def peek(self):
    while self.column >= len(self.line):
      try:
        line = self.readline()
      except StopIteration:
        line = ''
      if not line:
        self.error('EOF in multi-line f-string')
      self.line = line
      self.lines.append(line)
      self.lineno += 1
      self.column = 0
    return self.line[self.column]

  def scan_string(self):
    match = STRING_START.match(self.line, self.column)
    if match is None:
      self.error('expected string literal')
    prefix, quote = match.groups()
    prefix = (prefix or '').lower()
    formatted = 'f' in prefix
    raw = 'r' in prefix
    self.column = match.end()
    while True:
      char = self.peek()
      if self.line.startswith(quote, self.column):
        self.column += len(quote)
        return
      if char in '\r\n' and len(quote) == 1:
        self.error('unterminated string literal')
      if char == '\\':
        self.scan_escape(raw, formatted)
      elif formatted and char == '{':
        if self.line.startswith('{{', self.column):
          self.column += 2
        else:
          self.column += 1
          self.scan_replacement(quote, raw)
      elif formatted and char == '}':
        if not self.line.startswith('}}', self.column):
          self.error("f-string: single '}' is not allowed")
        self.column += 2
      else:
        self.column += 1

  def scan_escape(self, raw, formatted):
    self.column += 1
    char = self.peek()
    if formatted and char in '{}':
      # A backslash does not escape an f-string replacement-field delimiter.
      return
    if (formatted and not raw and char == 'N' and
        self.line.startswith('N{', self.column)):
      # Braces in a named Unicode escape are not replacement fields.
      self.column += 2
      while self.peek() != '}':
        if self.peek() in '\r\n':
          self.error('unterminated Unicode name escape')
        self.column += 1
      self.column += 1
    elif self.line.startswith('\r\n', self.column):
      self.column += 2
    else:
      self.column += 1

  def scan_replacement(self, quote, raw):
    brackets = []
    while True:
      char = self.peek()
      if STRING_START.match(self.line, self.column):
        self.scan_string()
      elif char == '#':
        # Quotes and braces in comments have no lexical significance.
        while self.peek() not in '\r\n':
          self.column += 1
      elif char == '\\':
        self.column += 1
        char = self.peek()
        if self.line.startswith('\r\n', self.column):
          self.column += 2
        elif char == '\n':
          self.column += 1
        else:
          self.error('unexpected character after line continuation character')
      elif char in _CLOSING:
        brackets.append(_CLOSING[char])
        self.column += 1
      elif char in ')]}':
        if brackets:
          if brackets.pop() != char:
            self.error('f-string: mismatched bracket in replacement field')
          self.column += 1
        elif char == '}':
          self.column += 1
          return
        else:
          self.error('f-string: unmatched closing bracket')
      elif not brackets and char == ':':
        self.column += 1
        self.scan_format_spec(quote, raw)
        return
      else:
        name = _NAME.match(self.line, self.column)
        self.column = name.end() if name else self.column + 1

  def scan_format_spec(self, quote, raw):
    while True:
      char = self.peek()
      if self.line.startswith(quote, self.column):
        self.error("f-string: expecting '}'")
      if char in '\r\n' and len(quote) == 1:
        self.error('f-string: newline in format specifier')
      if char == '}':
        self.column += 1
        return
      if char == '{':
        # Unlike literal text, format specs do not escape doubled braces.
        # For example, {{}} here is a replacement field containing a dict.
        self.column += 1
        self.scan_replacement(quote, raw)
      elif char == '\\':
        self.scan_escape(raw, True)
      else:
        self.column += 1
