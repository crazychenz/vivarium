#!/usr/bin/env bash

''':'
# Note, this script runs in both bash and python.

# Look for python
PYTHON=${PYTHON:-''}
if [ -z "$PYTHON" ]; then
    for pkg in python3 python; do
        if command -v "$pkg" &>/dev/null; then
            PYTHON=$pkg
            break
        fi
    done
fi
[ -z "$PYTHON" ] && { echo "python3 and python not found in $PATH" ; exit 1; }

# Look for pip
PIP=${PIP:-''}
if [ -z "$PIP" ]; then
    for pkg in pip3 pip; do
        if command -v "$pkg" &>/dev/null; then
            PIP=$pkg
            break
        fi
    done
fi
[ -z "$PIP" ] && { echo "pip and pip3 not found in $PATH" ; exit 1; }

for pkg in pyyaml jinja2; do
    if ! $PIP show "$pkg" &>/dev/null; then
        echo "\`do\` script missing Python package: $pkg"
        echo "Please run: \`pip install pyyaml\` or install with pkg manager"
        exit 1
    fi
done

command -v $PYTHON >/dev/null 2>&1 && exec $PYTHON "$0" "$@"
>&2 echo "error: cannot execute $PYTHON"
exit 1
'''


#!/usr/bin/env python3
"""
Pure Python implementation of the 'just' command runner.
Parses and executes justfiles with support for most just features.
"""

import os
import sys
import re
import subprocess
import shlex
import argparse
import hashlib
import uuid
import platform
import signal
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================================
# AST Node Definitions
# ============================================================================

@dataclass
class Recipe:
    """Represents a recipe in a justfile."""
    name: str
    parameters: List['Parameter'] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    body: List[str] = field(default_factory=list)
    doc_comments: List[str] = field(default_factory=list)
    quiet: bool = False
    private: bool = False
    no_cd: bool = False
    no_exit_message: bool = False
    shebang: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    line_prefixes: List[str] = field(default_factory=list)
    group: Optional[str] = None
    platform_conditions: List[str] = field(default_factory=list)


@dataclass
class Parameter:
    """Represents a recipe parameter."""
    name: str
    default: Optional[str] = None
    variadic: bool = False
    star: bool = False  # *
    plus: bool = False  # +


@dataclass
class Assignment:
    """Represents a variable assignment."""
    name: str
    value: str


@dataclass
class Alias:
    """Represents a recipe alias."""
    name: str
    target: str


@dataclass
class Import:
    """Represents an import statement."""
    path: str
    optional: bool = False


# ============================================================================
# Lexer
# ============================================================================

class Token:
    def __init__(self, type_: str, value: str, line: int, column: int):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Token({self.type}, {self.value!r}, {self.line}, {self.column})"


class Lexer:
    """Tokenizes justfile content."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []

    def current_char(self) -> Optional[str]:
        if self.pos >= len(self.text):
            return None
        return self.text[self.pos]

    def peek_char(self, offset: int = 1) -> Optional[str]:
        pos = self.pos + offset
        if pos >= len(self.text):
            return None
        return self.text[pos]

    def advance(self):
        if self.pos < len(self.text):
            if self.text[self.pos] == '\n':
                self.line += 1
                self.column = 1
            else:
                self.column += 1
            self.pos += 1

    def skip_whitespace(self, skip_newline: bool = False):
        while self.current_char() in (' ', '\t', '\r'):
            self.advance()
        if skip_newline:
            while self.current_char() in (' ', '\t', '\r', '\n'):
                self.advance()

    def skip_comment(self):
        if self.current_char() == '#':
            while self.current_char() and self.current_char() != '\n':
                self.advance()

    def read_string(self) -> str:
        """Read a quoted string."""
        quote = self.current_char()
        self.advance()  # Skip opening quote

        value = []
        while self.current_char() and self.current_char() != quote:
            if self.current_char() == '\\' and self.peek_char() in (quote, '\\', 'n', 't', 'r', '{'):
                self.advance()
                escape_char = self.current_char()
                if escape_char == 'n':
                    value.append('\n')
                elif escape_char == 't':
                    value.append('\t')
                elif escape_char == 'r':
                    value.append('\r')
                elif escape_char == '{' and self.peek_char() == '{':
                    value.append('{{')
                    self.advance()
                else:
                    value.append(escape_char)
                self.advance()
            else:
                value.append(self.current_char())
                self.advance()

        if self.current_char() == quote:
            self.advance()  # Skip closing quote

        return ''.join(value)

    def read_raw_string(self) -> str:
        """Read a raw string (x"..." or x'...')."""
        self.advance()  # Skip 'x'
        quote = self.current_char()
        self.advance()  # Skip opening quote

        value = []
        while self.current_char() and self.current_char() != quote:
            value.append(self.current_char())
            self.advance()

        if self.current_char() == quote:
            self.advance()  # Skip closing quote

        return ''.join(value)

    def read_identifier(self) -> str:
        """Read an identifier or keyword."""
        value = []
        while self.current_char() and (self.current_char().isalnum() or self.current_char() in ('_', '-')):
            value.append(self.current_char())
            self.advance()
        return ''.join(value)

    def tokenize(self) -> List[Token]:
        """Tokenize the entire justfile."""
        while self.pos < len(self.text):
            self.skip_whitespace()

            if self.current_char() is None:
                break

            # Skip comments
            if self.current_char() == '#':
                self.skip_comment()
                continue

            # Newline
            if self.current_char() == '\n':
                self.advance()
                continue

            # String literals
            if self.current_char() in ('"', "'"):
                start_col = self.column
                value = self.read_string()
                self.tokens.append(Token('STRING', value, self.line, start_col))
                continue

            # Raw strings
            if self.current_char() == 'x' and self.peek_char() in ('"', "'"):
                start_col = self.column
                value = self.read_raw_string()
                self.tokens.append(Token('STRING', value, self.line, start_col))
                continue

            # Backtick strings
            if self.current_char() == '`':
                start_col = self.column
                self.advance()
                value = []
                while self.current_char() and self.current_char() != '`':
                    value.append(self.current_char())
                    self.advance()
                if self.current_char() == '`':
                    self.advance()
                self.tokens.append(Token('BACKTICK', ''.join(value), self.line, start_col))
                continue

            # Operators and special characters
            if self.current_char() == ':' and self.peek_char() == '=':
                start_col = self.column
                self.advance()
                self.advance()
                self.tokens.append(Token('ASSIGN', ':=', self.line, start_col))
                continue

            if self.current_char() == ':':
                start_col = self.column
                self.advance()
                self.tokens.append(Token('COLON', ':', self.line, start_col))
                continue

            if self.current_char() == '=':
                start_col = self.column
                if self.peek_char() == '=':
                    self.advance()
                    self.advance()
                    self.tokens.append(Token('EQ', '==', self.line, start_col))
                elif self.peek_char() == '~':
                    self.advance()
                    self.advance()
                    self.tokens.append(Token('REGEX_MATCH', '=~', self.line, start_col))
                else:
                    self.advance()
                    self.tokens.append(Token('EQUALS', '=', self.line, start_col))
                continue

            if self.current_char() == '!' and self.peek_char() == '=':
                start_col = self.column
                self.advance()
                self.advance()
                self.tokens.append(Token('NE', '!=', self.line, start_col))
                continue

            if self.current_char() == '|' and self.peek_char() == '|':
                start_col = self.column
                self.advance()
                self.advance()
                self.tokens.append(Token('OR', '||', self.line, start_col))
                continue

            if self.current_char() == '&' and self.peek_char() == '&':
                start_col = self.column
                self.advance()
                self.advance()
                self.tokens.append(Token('AND', '&&', self.line, start_col))
                continue

            # Single character tokens
            single_char_tokens = {
                '(': 'LPAREN', ')': 'RPAREN',
                '[': 'LBRACKET', ']': 'RBRACKET',
                '{': 'LBRACE', '}': 'RBRACE',
                ',': 'COMMA', '@': 'AT',
                '+': 'PLUS', '/': 'SLASH',
                '*': 'STAR', '!': 'NOT'
            }

            if self.current_char() in single_char_tokens:
                start_col = self.column
                char = self.current_char()
                self.advance()
                self.tokens.append(Token(single_char_tokens[char], char, self.line, start_col))
                continue

            # Identifiers and keywords
            if self.current_char().isalpha() or self.current_char() == '_':
                start_col = self.column
                value = self.read_identifier()

                keywords = {'set', 'alias', 'export', 'import', 'mod', 'if', 'else'}
                token_type = 'KEYWORD' if value in keywords else 'IDENT'
                self.tokens.append(Token(token_type, value, self.line, start_col))
                continue

            # Unknown character - skip it
            self.advance()

        return self.tokens


# ============================================================================
# Parser
# ============================================================================

class Parser:
    """Parses justfile tokens into an AST."""

    def __init__(self, text: str, filepath: str = "justfile"):
        self.text = text
        self.filepath = filepath
        self.lines = text.split('\n')
        self.recipes: Dict[str, Recipe] = {}
        self.assignments: Dict[str, str] = {}
        self.aliases: Dict[str, str] = {}
        self.imports: List[Import] = []
        self.settings: Dict[str, Any] = {}
        self.current_line = 0

    def parse(self):
        """Parse the justfile."""
        self.current_line = 0

        while self.current_line < len(self.lines):
            line = self.lines[self.current_line].rstrip()

            # Skip empty lines and comments
            if not line or line.lstrip().startswith('#'):
                self.current_line += 1
                continue

            # Settings
            if line.startswith('set '):
                self.parse_setting(line)
                self.current_line += 1
                continue

            # Aliases
            if line.startswith('alias '):
                self.parse_alias(line)
                self.current_line += 1
                continue

            # Exports
            if line.startswith('export '):
                self.parse_export(line)
                self.current_line += 1
                continue

            # Imports
            if line.startswith('import '):
                self.parse_import(line)
                self.current_line += 1
                continue

            # Assignments
            if ':=' in line and not line.startswith((' ', '\t', '@', '[', '-')):
                self.parse_assignment(line)
                self.current_line += 1
                continue

            # Recipes (with attributes or direct)
            if line.startswith('[') or (not line.startswith((' ', '\t')) and ':' in line):
                self.parse_recipe()
                continue

            self.current_line += 1

    def parse_setting(self, line: str):
        """Parse a setting line."""
        match = re.match(r'set\s+([a-z-]+)\s*:=\s*(.+)', line)
        if match:
            name, value = match.groups()
            self.settings[name] = self.evaluate_expression(value.strip())

    def parse_alias(self, line: str):
        """Parse an alias."""
        match = re.match(r'alias\s+(\S+)\s*:=\s*(\S+)', line)
        if match:
            alias_name, target = match.groups()
            self.aliases[alias_name] = target

    def parse_export(self, line: str):
        """Parse an export."""
        match = re.match(r'export\s+(\w+)\s*:=\s*(.+)', line)
        if match:
            name, value = match.groups()
            value = self.evaluate_expression(value.strip())
            self.assignments[name] = value
            os.environ[name] = value
        else:
            match = re.match(r'export\s+(\w+)', line)
            if match:
                name = match.group(1)
                if name in os.environ:
                    self.assignments[name] = os.environ[name]

    def parse_import(self, line: str):
        """Parse an import."""
        match = re.match(r'import\s+(\?)?(.+)', line)
        if match:
            optional, path = match.groups()
            path = path.strip().strip('"\'')
            self.imports.append(Import(path, optional is not None))

    def parse_assignment(self, line: str):
        """Parse a variable assignment."""
        match = re.match(r'(\w+)\s*:=\s*(.+)', line)
        if match:
            name, value = match.groups()
            self.assignments[name] = value.strip()

    def parse_recipe(self):
        """Parse a recipe definition."""
        # Parse attributes
        attributes = {}
        platform_conditions = []

        while self.current_line < len(self.lines):
            line = self.lines[self.current_line].rstrip()
            if line.startswith('['):
                attrs = self.parse_attributes(line)
                attributes.update(attrs)
                # Extract platform conditions
                for attr in ['linux', 'macos', 'unix', 'windows']:
                    if attr in attrs:
                        platform_conditions.append(attr)
                self.current_line += 1
            else:
                break

        # Parse recipe header
        if self.current_line >= len(self.lines):
            return

        line = self.lines[self.current_line].rstrip()

        # Check for @ prefix (quiet)
        quiet = line.startswith('@')
        if quiet:
            line = line[1:].lstrip()

        # Extract recipe name, parameters, and dependencies
        if ':' not in line:
            self.current_line += 1
            return

        header_part, _, deps_part = line.partition(':')
        header_part = header_part.strip()
        deps_part = deps_part.strip()

        # Parse recipe name and parameters
        parts = header_part.split()
        if not parts:
            self.current_line += 1
            return

        recipe_name = parts[0]
        parameters = self.parse_parameters(parts[1:])

        # Parse dependencies
        dependencies = deps_part.split() if deps_part else []

        self.current_line += 1

        # Parse recipe body
        body = []
        doc_comments = []
        line_prefixes = []
        shebang = None

        base_indent = None
        while self.current_line < len(self.lines):
            line = self.lines[self.current_line]

            # Check if line is indented
            if line and not line[0].isspace():
                break

            stripped = line.lstrip()
            if not stripped:
                self.current_line += 1
                continue

            # Determine base indentation
            if base_indent is None and stripped:
                base_indent = len(line) - len(stripped)

            # Check for doc comments
            if stripped.startswith('#') and not stripped.startswith('#!'):
                doc_comments.append(stripped[1:].strip())
                self.current_line += 1
                continue

            # Check for shebang
            if stripped.startswith('#!'):
                shebang = stripped
                self.current_line += 1
                # Read all following lines for shebang script
                while self.current_line < len(self.lines):
                    line = self.lines[self.current_line]
                    if line and not line[0].isspace():
                        break
                    body.append(line[base_indent:] if base_indent and len(line) > base_indent else line)
                    self.current_line += 1
                break

            # Parse line prefix
            prefix = ''
            if stripped.startswith('@-') or stripped.startswith('-@'):
                prefix = stripped[:2]
                stripped = stripped[2:].lstrip()
            elif stripped.startswith('@'):
                prefix = '@'
                stripped = stripped[1:].lstrip()
            elif stripped.startswith('-'):
                prefix = '-'
                stripped = stripped[1:].lstrip()

            line_prefixes.append(prefix)
            body.append(stripped)
            self.current_line += 1

        # Create recipe
        recipe = Recipe(
            name=recipe_name,
            parameters=parameters,
            dependencies=dependencies,
            body=body,
            doc_comments=doc_comments,
            quiet=quiet or attributes.get('private', False),
            private=attributes.get('private', False),
            no_cd=attributes.get('no-cd', False),
            no_exit_message=attributes.get('no-exit-message', False),
            shebang=shebang,
            attributes=attributes,
            line_prefixes=line_prefixes,
            group=attributes.get('group'),
            platform_conditions=platform_conditions
        )

        self.recipes[recipe_name] = recipe

    def parse_attributes(self, line: str) -> Dict[str, Any]:
        """Parse recipe attributes."""
        attrs = {}
        match = re.match(r'\[(.*?)\]', line)
        if match:
            attr_str = match.group(1)
            for attr in attr_str.split(','):
                attr = attr.strip()

                # Handle group attribute
                if attr.startswith('group('):
                    group_match = re.match(r'group\(["\'](.+?)["\']\)', attr)
                    if group_match:
                        attrs['group'] = group_match.group(1)

                # Handle confirm attribute
                elif attr.startswith('confirm'):
                    confirm_match = re.match(r'confirm(?:\(["\'](.+?)["\']\))?', attr)
                    if confirm_match:
                        attrs['confirm'] = confirm_match.group(1) or 'Run this recipe?'

                # Simple boolean attributes
                else:
                    attrs[attr] = True

        return attrs

    def parse_parameters(self, param_parts: List[str]) -> List[Parameter]:
        """Parse recipe parameters."""
        parameters = []

        for part in param_parts:
            # Variadic parameter: *args or *args=default
            if part.startswith('*'):
                if part == '*':
                    parameters.append(Parameter('', variadic=True, star=True))
                elif part == '+':
                    parameters.append(Parameter('', variadic=True, plus=True))
                else:
                    rest = part[1:]
                    if '=' in rest:
                        name, default = rest.split('=', 1)
                        parameters.append(Parameter(name, default.strip('"\''), variadic=True))
                    else:
                        parameters.append(Parameter(rest, variadic=True))

            # Regular parameter with default
            elif '=' in part:
                name, default = part.split('=', 1)
                parameters.append(Parameter(name, default.strip('"\'')))

            # Regular parameter
            else:
                parameters.append(Parameter(part))

        return parameters

    def evaluate_expression(self, expr: str) -> str:
        """Evaluate a simple expression."""
        expr = expr.strip()

        # Remove quotes if present
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        return expr


# ============================================================================
# Expression Evaluator
# ============================================================================

class ExpressionEvaluator:
    """Evaluates expressions in justfiles."""

    def __init__(self, context: Dict[str, str], justfile_path: str):
        self.context = context
        self.justfile_path = Path(justfile_path).resolve()
        self.justfile_dir = self.justfile_path.parent

    def evaluate(self, expr: str) -> str:
        """Evaluate an expression."""
        expr = expr.strip()

        # Handle string literals
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return self.process_string(expr[1:-1])

        # Handle backticks
        if expr.startswith('`') and expr.endswith('`'):
            return self.execute_backtick(expr[1:-1])

        # Handle function calls
        if '(' in expr and expr.endswith(')'):
            return self.evaluate_function(expr)

        # Handle conditional expressions
        if ' if ' in expr:
            return self.evaluate_conditional(expr)

        # Handle binary operations
        if '==' in expr or '!=' in expr or '=~' in expr:
            return self.evaluate_comparison(expr)

        if '||' in expr or '&&' in expr:
            return self.evaluate_logical(expr)

        if '+' in expr or '/' in expr:
            return self.evaluate_arithmetic(expr)

        # Variable reference
        if expr in self.context:
            return self.context[expr]

        # Environment variable
        if expr in os.environ:
            return os.environ[expr]

        return expr

    def process_string(self, s: str) -> str:
        """Process string interpolations."""
        result = []
        i = 0
        while i < len(s):
            if i < len(s) - 1 and s[i:i+2] == '{{':
                # Find closing }}
                j = s.find('}}', i + 2)
                if j != -1:
                    expr = s[i+2:j]
                    result.append(self.evaluate(expr))
                    i = j + 2
                else:
                    result.append(s[i])
                    i += 1
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)

    def execute_backtick(self, cmd: str) -> str:
        """Execute a backtick command."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.justfile_dir
            )
            return result.stdout.strip()
        except Exception:
            return ''

    def evaluate_function(self, expr: str) -> str:
        """Evaluate a function call."""
        match = re.match(r'(\w+)\((.*)\)', expr)
        if not match:
            return expr

        func_name, args_str = match.groups()
        args = self.parse_arguments(args_str)

        # Evaluate arguments
        evaluated_args = [self.evaluate(arg) for arg in args]

        return self.call_function(func_name, evaluated_args)

    def parse_arguments(self, args_str: str) -> List[str]:
        """Parse function arguments."""
        if not args_str.strip():
            return []

        args = []
        current_arg = []
        depth = 0
        in_string = False
        string_char = None

        for char in args_str:
            if char in ('"', "'") and not in_string:
                in_string = True
                string_char = char
                current_arg.append(char)
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                current_arg.append(char)
            elif char == '(' and not in_string:
                depth += 1
                current_arg.append(char)
            elif char == ')' and not in_string:
                depth -= 1
                current_arg.append(char)
            elif char == ',' and depth == 0 and not in_string:
                args.append(''.join(current_arg).strip())
                current_arg = []
            else:
                current_arg.append(char)

        if current_arg:
            args.append(''.join(current_arg).strip())

        return args

    def call_function(self, func_name: str, args: List[str]) -> str:
        """Call a built-in function."""
        functions = {
            'env_var': self.func_env_var,
            'env_var_or_default': self.func_env_var_or_default,
            'env': self.func_env,
            'justfile': self.func_justfile,
            'justfile_directory': self.func_justfile_directory,
            'source_directory': self.func_source_directory,
            'source_file': self.func_source_file,
            'invocation_directory': self.func_invocation_directory,
            'invocation_directory_native': self.func_invocation_directory_native,
            'home_directory': self.func_home_directory,
            'absolute_path': self.func_absolute_path,
            'canonicalize': self.func_canonicalize,
            'file_name': self.func_file_name,
            'file_stem': self.func_file_stem,
            'parent_directory': self.func_parent_directory,
            'extension': self.func_extension,
            'without_extension': self.func_without_extension,
            'path_exists': self.func_path_exists,
            'join': self.func_join,
            'replace': self.func_replace,
            'replace_regex': self.func_replace_regex,
            'trim': self.func_trim,
            'trim_start': self.func_trim_start,
            'trim_end': self.func_trim_end,
            'trim_start_match': self.func_trim_start_match,
            'trim_end_match': self.func_trim_end_match,
            'trim_start_matches': self.func_trim_start_matches,
            'trim_end_matches': self.func_trim_end_matches,
            'uppercase': self.func_uppercase,
            'lowercase': self.func_lowercase,
            'capitalize': self.func_capitalize,
            'titlecase': self.func_titlecase,
            'kebabcase': self.func_kebabcase,
            'snakecase': self.func_snakecase,
            'shoutcase': self.func_shoutcase,
            'lowercamelcase': self.func_lowercamelcase,
            'uppercamelcase': self.func_uppercamelcase,
            'quote': self.func_quote,
            'shell': self.func_shell,
            'sha256': self.func_sha256,
            'sha256_file': self.func_sha256_file,
            'blake3': self.func_blake3,
            'blake3_file': self.func_blake3_file,
            'uuid': self.func_uuid,
            'datetime': self.func_datetime,
            'datetime_utc': self.func_datetime_utc,
            'os': self.func_os,
            'os_family': self.func_os_family,
            'arch': self.func_arch,
            'num_cpus': self.func_num_cpus,
            'just_executable': self.func_just_executable,
            'just_pid': self.func_just_pid,
            'append': self.func_append,
            'prepend': self.func_prepend,
            'clean': self.func_clean,
            'error': self.func_error,
        }

        if func_name in functions:
            return functions[func_name](args)

        return f"{func_name}({', '.join(args)})"

    # Function implementations
    def func_env_var(self, args: List[str]) -> str:
        if args and args[0] in os.environ:
            return os.environ[args[0]]
        raise ValueError(f"Environment variable {args[0]} not set")

    def func_env_var_or_default(self, args: List[str]) -> str:
        if len(args) >= 2:
            return os.environ.get(args[0], args[1])
        return os.environ.get(args[0], '') if args else ''

    def func_env(self, args: List[str]) -> str:
        if len(args) >= 2:
            return os.environ.get(args[0], args[1])
        return os.environ.get(args[0], '') if args else ''

    def func_justfile(self, args: List[str]) -> str:
        return str(self.justfile_path)

    def func_justfile_directory(self, args: List[str]) -> str:
        return str(self.justfile_dir)

    def func_source_directory(self, args: List[str]) -> str:
        return str(self.justfile_dir)

    def func_source_file(self, args: List[str]) -> str:
        return str(self.justfile_path)

    def func_invocation_directory(self, args: List[str]) -> str:
        return os.getcwd()

    def func_invocation_directory_native(self, args: List[str]) -> str:
        return os.getcwd()

    def func_home_directory(self, args: List[str]) -> str:
        return str(Path.home())

    def func_absolute_path(self, args: List[str]) -> str:
        if args:
            return str(Path(args[0]).resolve())
        return ''

    def func_canonicalize(self, args: List[str]) -> str:
        if args:
            return str(Path(args[0]).resolve())
        return ''

    def func_file_name(self, args: List[str]) -> str:
        if args:
            return Path(args[0]).name
        return ''

    def func_file_stem(self, args: List[str]) -> str:
        if args:
            return Path(args[0]).stem
        return ''

    def func_parent_directory(self, args: List[str]) -> str:
        if args:
            return str(Path(args[0]).parent)
        return ''

    def func_extension(self, args: List[str]) -> str:
        if args:
            ext = Path(args[0]).suffix
            return ext[1:] if ext else ''
        return ''

    def func_without_extension(self, args: List[str]) -> str:
        if args:
            p = Path(args[0])
            return str(p.parent / p.stem)
        return ''

    def func_path_exists(self, args: List[str]) -> str:
        if args:
            return 'true' if Path(args[0]).exists() else 'false'
        return 'false'

    def func_join(self, args: List[str]) -> str:
        if len(args) >= 2:
            return args[1].join(args[0].split())
        return args[0] if args else ''

    def func_replace(self, args: List[str]) -> str:
        if len(args) >= 3:
            return args[0].replace(args[1], args[2])
        return args[0] if args else ''

    def func_replace_regex(self, args: List[str]) -> str:
        if len(args) >= 3:
            return re.sub(args[1], args[2], args[0])
        return args[0] if args else ''

    def func_trim(self, args: List[str]) -> str:
        return args[0].strip() if args else ''

    def func_trim_start(self, args: List[str]) -> str:
        return args[0].lstrip() if args else ''

    def func_trim_end(self, args: List[str]) -> str:
        return args[0].rstrip() if args else ''

    def func_trim_start_match(self, args: List[str]) -> str:
        if len(args) >= 2 and args[0].startswith(args[1]):
            return args[0][len(args[1]):]
        return args[0] if args else ''

    def func_trim_end_match(self, args: List[str]) -> str:
        if len(args) >= 2 and args[0].endswith(args[1]):
            return args[0][:-len(args[1])]
        return args[0] if args else ''

    def func_trim_start_matches(self, args: List[str]) -> str:
        if len(args) >= 2:
            s = args[0]
            while s.startswith(args[1]):
                s = s[len(args[1]):]
            return s
        return args[0] if args else ''

    def func_trim_end_matches(self, args: List[str]) -> str:
        if len(args) >= 2:
            s = args[0]
            while s.endswith(args[1]):
                s = s[:-len(args[1])]
            return s
        return args[0] if args else ''

    def func_uppercase(self, args: List[str]) -> str:
        return args[0].upper() if args else ''

    def func_lowercase(self, args: List[str]) -> str:
        return args[0].lower() if args else ''

    def func_capitalize(self, args: List[str]) -> str:
        return args[0].capitalize() if args else ''

    def func_titlecase(self, args: List[str]) -> str:
        return args[0].title() if args else ''

    def func_kebabcase(self, args: List[str]) -> str:
        if args:
            s = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', args[0])
            s = re.sub(r'[\s_]+', '-', s)
            return s.lower()
        return ''

    def func_snakecase(self, args: List[str]) -> str:
        if args:
            s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', args[0])
            s = re.sub(r'[\s-]+', '_', s)
            return s.lower()
        return ''

    def func_shoutcase(self, args: List[str]) -> str:
        return self.func_snakecase(args).upper()

    def func_lowercamelcase(self, args: List[str]) -> str:
        if args:
            words = re.split(r'[\s_-]+', args[0])
            if words:
                return words[0].lower() + ''.join(w.capitalize() for w in words[1:])
        return ''

    def func_uppercamelcase(self, args: List[str]) -> str:
        if args:
            words = re.split(r'[\s_-]+', args[0])
            return ''.join(w.capitalize() for w in words)
        return ''

    def func_quote(self, args: List[str]) -> str:
        if args:
            return shlex.quote(args[0])
        return ''

    def func_shell(self, args: List[str]) -> str:
        if args:
            try:
                result = subprocess.run(
                    args[0],
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=self.justfile_dir
                )
                return result.stdout.strip()
            except Exception:
                return ''
        return ''

    def func_sha256(self, args: List[str]) -> str:
        if args:
            return hashlib.sha256(args[0].encode()).hexdigest()
        return ''

    def func_sha256_file(self, args: List[str]) -> str:
        if args:
            try:
                with open(args[0], 'rb') as f:
                    return hashlib.sha256(f.read()).hexdigest()
            except Exception:
                return ''
        return ''

    def func_blake3(self, args: List[str]) -> str:
        # Blake3 not in stdlib, use sha256 as fallback
        return self.func_sha256(args)

    def func_blake3_file(self, args: List[str]) -> str:
        # Blake3 not in stdlib, use sha256 as fallback
        return self.func_sha256_file(args)

    def func_uuid(self, args: List[str]) -> str:
        return str(uuid.uuid4())

    def func_datetime(self, args: List[str]) -> str:
        fmt = args[0] if args else '%Y-%m-%d %H:%M:%S'
        return datetime.now().strftime(fmt)

    def func_datetime_utc(self, args: List[str]) -> str:
        fmt = args[0] if args else '%Y-%m-%d %H:%M:%S'
        return datetime.utcnow().strftime(fmt)

    def func_os(self, args: List[str]) -> str:
        return platform.system().lower()

    def func_os_family(self, args: List[str]) -> str:
        system = platform.system().lower()
        if system in ('linux', 'darwin'):
            return 'unix'
        return system

    def func_arch(self, args: List[str]) -> str:
        return platform.machine()

    def func_num_cpus(self, args: List[str]) -> str:
        return str(os.cpu_count() or 1)

    def func_just_executable(self, args: List[str]) -> str:
        return sys.argv[0]

    def func_just_pid(self, args: List[str]) -> str:
        return str(os.getpid())

    def func_append(self, args: List[str]) -> str:
        if len(args) >= 2:
            return args[1] + args[0]
        return args[0] if args else ''

    def func_prepend(self, args: List[str]) -> str:
        if len(args) >= 2:
            return args[0] + args[1]
        return args[0] if args else ''

    def func_clean(self, args: List[str]) -> str:
        if args:
            return ' '.join(args[0].split())
        return ''

    def func_error(self, args: List[str]) -> str:
        msg = args[0] if args else 'error'
        raise RuntimeError(msg)

    def evaluate_conditional(self, expr: str) -> str:
        """Evaluate conditional expression: value if condition else other_value"""
        match = re.match(r'(.+?)\s+if\s+(.+?)\s+else\s+(.+)', expr)
        if match:
            true_val, condition, false_val = match.groups()
            cond_result = self.evaluate(condition.strip())
            if self.is_truthy(cond_result):
                return self.evaluate(true_val.strip())
            else:
                return self.evaluate(false_val.strip())
        return expr

    def evaluate_comparison(self, expr: str) -> str:
        """Evaluate comparison expressions."""
        for op in ['==', '!=', '=~']:
            if op in expr:
                left, right = expr.split(op, 1)
                left_val = self.evaluate(left.strip())
                right_val = self.evaluate(right.strip())

                if op == '==':
                    return 'true' if left_val == right_val else 'false'
                elif op == '!=':
                    return 'true' if left_val != right_val else 'false'
                elif op == '=~':
                    return 'true' if re.search(right_val, left_val) else 'false'
        return expr

    def evaluate_logical(self, expr: str) -> str:
        """Evaluate logical expressions."""
        if '||' in expr:
            parts = expr.split('||')
            for part in parts:
                if self.is_truthy(self.evaluate(part.strip())):
                    return 'true'
            return 'false'

        if '&&' in expr:
            parts = expr.split('&&')
            for part in parts:
                if not self.is_truthy(self.evaluate(part.strip())):
                    return 'false'
            return 'true'

        return expr

    def evaluate_arithmetic(self, expr: str) -> str:
        """Evaluate arithmetic expressions."""
        if '/' in expr:
            parts = expr.split('/')
            result = self.evaluate(parts[0].strip())
            for part in parts[1:]:
                result = str(Path(result) / self.evaluate(part.strip()))
            return result

        if '+' in expr:
            parts = [self.evaluate(p.strip()) for p in expr.split('+')]
            return ''.join(parts)

        return expr

    def is_truthy(self, value: str) -> bool:
        """Check if a value is truthy."""
        value = value.strip().lower()
        return value not in ('', 'false', '0', 'no', 'none')


# ============================================================================
# Justfile Runner
# ============================================================================

class JustRunner:
    """Executes recipes from a justfile."""

    def __init__(self, parser: Parser, working_dir: Optional[Path] = None):
        self.parser = parser
        self.working_dir = working_dir or Path.cwd()
        self.justfile_dir = Path(parser.filepath).parent.resolve()
        self.executed_recipes: Set[str] = set()
        self.signal_handler_installed = False

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        if not self.signal_handler_installed:
            def signal_handler(signum, frame):
                print(f"\nReceived signal {signum}, stopping...")
                sys.exit(1)

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            self.signal_handler_installed = True

    def list_recipes(self, show_private: bool = False):
        """List all recipes."""
        print("Available recipes:")

        # Group recipes
        groups: Dict[Optional[str], List[Recipe]] = {}
        for recipe in self.parser.recipes.values():
            if recipe.private and not show_private:
                continue

            group = recipe.group
            if group not in groups:
                groups[group] = []
            groups[group].append(recipe)

        # Print ungrouped recipes first
        if None in groups:
            for recipe in sorted(groups[None], key=lambda r: r.name):
                self.print_recipe_info(recipe)
            print()

        # Print grouped recipes
        for group_name in sorted(g for g in groups.keys() if g is not None):
            print(f"[{group_name}]")
            for recipe in sorted(groups[group_name], key=lambda r: r.name):
                self.print_recipe_info(recipe)
            print()

    def print_recipe_info(self, recipe: Recipe):
        """Print information about a recipe."""
        params = ' '.join(p.name or ('*' if p.star else '+') for p in recipe.parameters)
        line = f"    {recipe.name}"
        if params:
            line += f" {params}"

        if recipe.doc_comments:
            line += f" # {recipe.doc_comments[0]}"

        print(line)

    def run_recipe(self, recipe_name: str, args: List[str] = None):
        """Run a single recipe with arguments."""
        args = args or []

        # Resolve alias
        if recipe_name in self.parser.aliases:
            recipe_name = self.parser.aliases[recipe_name]

        # Check if recipe exists
        if recipe_name not in self.parser.recipes:
            print(f"error: Recipe '{recipe_name}' not found", file=sys.stderr)
            sys.exit(1)

        recipe = self.parser.recipes[recipe_name]

        # Check platform conditions
        if recipe.platform_conditions:
            current_platform = platform.system().lower()
            platform_map = {
                'linux': 'linux',
                'darwin': 'macos',
                'windows': 'windows'
            }
            current = platform_map.get(current_platform, current_platform)

            matches = False
            for condition in recipe.platform_conditions:
                if condition == current:
                    matches = True
                    break
                if condition == 'unix' and current in ('linux', 'macos'):
                    matches = True
                    break

            if not matches:
                if not recipe.no_exit_message:
                    print(f"Recipe '{recipe_name}' is not available on this platform")
                return

        # Check for confirmation
        if 'confirm' in recipe.attributes:
            prompt = recipe.attributes['confirm']
            response = input(f"{prompt} [y/N] ")
            if response.lower() not in ('y', 'yes'):
                print("Cancelled")
                return

        # Run dependencies first
        for dep in recipe.dependencies:
            if dep not in self.executed_recipes:
                self.run_recipe(dep, [])

        # Bind parameters
        context = dict(self.parser.assignments)
        context.update(os.environ)

        self.bind_parameters(recipe, args, context)

        # Execute recipe
        self.execute_recipe(recipe, context)

        self.executed_recipes.add(recipe_name)

    def bind_parameters(self, recipe: Recipe, args: List[str], context: Dict[str, str]):
        """Bind arguments to recipe parameters."""
        arg_index = 0

        for i, param in enumerate(recipe.parameters):
            if param.star or param.plus:
                # Collect all remaining arguments
                remaining = args[arg_index:]
                if param.plus and not remaining:
                    print(f"error: Recipe '{recipe.name}' requires at least one argument", file=sys.stderr)
                    sys.exit(1)
                context['@'] = ' '.join(remaining)
                for j, arg in enumerate(remaining):
                    context[str(j)] = arg
                break

            elif param.variadic:
                # Collect remaining arguments
                remaining = args[arg_index:]
                context[param.name] = ' '.join(remaining)
                break

            elif arg_index < len(args):
                # Regular parameter with provided argument
                context[param.name] = args[arg_index]
                arg_index += 1

            elif param.default is not None:
                # Use default value
                evaluator = ExpressionEvaluator(context, self.parser.filepath)
                context[param.name] = evaluator.evaluate(param.default)

            else:
                # Required parameter missing
                print(f"error: Recipe '{recipe.name}' missing required parameter '{param.name}'", file=sys.stderr)
                sys.exit(1)

    def execute_recipe(self, recipe: Recipe, context: Dict[str, str]):
        """Execute a recipe's body."""
        if not recipe.body:
            return

        # Setup signal handlers
        self.setup_signal_handlers()

        # Determine working directory
        cwd = self.working_dir if recipe.no_cd else self.justfile_dir

        # Handle shebang recipes
        if recipe.shebang:
            self.execute_shebang_recipe(recipe, context, cwd)
        else:
            self.execute_normal_recipe(recipe, context, cwd)

    def execute_shebang_recipe(self, recipe: Recipe, context: Dict[str, str], cwd: Path):
        """Execute a shebang recipe."""
        # Create temporary script
        script_content = [recipe.shebang] + recipe.body

        # Evaluate expressions in script
        evaluator = ExpressionEvaluator(context, self.parser.filepath)
        evaluated_script = []
        for line in script_content:
            evaluated_line = self.evaluate_line(line, evaluator)
            evaluated_script.append(evaluated_line)

        # Write to temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write('\n'.join(evaluated_script))
            script_path = f.name

        try:
            # Make executable
            os.chmod(script_path, 0o755)

            # Execute
            result = subprocess.run(
                [script_path],
                cwd=cwd,
                env=context
            )

            if result.returncode != 0:
                if not recipe.no_exit_message:
                    print(f"error: Recipe '{recipe.name}' failed with exit code {result.returncode}", file=sys.stderr)
                sys.exit(result.returncode)

        finally:
            # Clean up
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def execute_normal_recipe(self, recipe: Recipe, context: Dict[str, str], cwd: Path):
        """Execute a normal recipe line by line."""
        evaluator = ExpressionEvaluator(context, self.parser.filepath)

        for i, line in enumerate(recipe.body):
            prefix = recipe.line_prefixes[i] if i < len(recipe.line_prefixes) else ''

            # Evaluate expressions
            evaluated_line = self.evaluate_line(line, evaluator)

            # Check for empty line
            if not evaluated_line.strip():
                continue

            # Print command if not quiet
            if '@' not in prefix and not recipe.quiet:
                print(evaluated_line)

            # Execute command
            try:
                result = subprocess.run(
                    evaluated_line,
                    shell=True,
                    cwd=cwd,
                    env=context
                )

                # Check for errors (unless prefixed with -)
                if result.returncode != 0 and '-' not in prefix:
                    if not recipe.no_exit_message:
                        print(f"error: Recipe '{recipe.name}' failed with exit code {result.returncode}", file=sys.stderr)
                    sys.exit(result.returncode)

            except Exception as e:
                if '-' not in prefix:
                    print(f"error: {e}", file=sys.stderr)
                    sys.exit(1)

    def evaluate_line(self, line: str, evaluator: ExpressionEvaluator) -> str:
        """Evaluate expressions in a line."""
        result = []
        i = 0
        while i < len(line):
            if i < len(line) - 1 and line[i:i+2] == '{{':
                # Find closing }}
                j = line.find('}}', i + 2)
                if j != -1:
                    expr = line[i+2:j]
                    result.append(evaluator.evaluate(expr))
                    i = j + 2
                else:
                    result.append(line[i])
                    i += 1
            else:
                result.append(line[i])
                i += 1
        return ''.join(result)


# ============================================================================
# Main Function
# ============================================================================

def find_justfile(start_dir: Path = None) -> Optional[Path]:
    """Find a justfile in the current or parent directories."""
    current = start_dir or Path.cwd()

    while True:
        for name in ('justfile', 'Justfile', '.justfile'):
            justfile_path = current / name
            if justfile_path.exists():
                return justfile_path

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Just command runner - execute commands from justfiles',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '-f', '--justfile',
        help='Use a specific justfile',
        default=None
    )

    parser.add_argument(
        '-d', '--working-directory',
        help='Use a specific working directory',
        default=None
    )

    parser.add_argument(
        '-l', '--list',
        action='store_true',
        help='List available recipes'
    )

    parser.add_argument(
        '--show-private',
        action='store_true',
        help='Show private recipes when listing'
    )

    parser.add_argument(
        '--dump',
        action='store_true',
        help='Dump justfile as JSON'
    )

    parser.add_argument(
        'recipe',
        nargs='?',
        help='Recipe to run'
    )

    parser.add_argument(
        'args',
        nargs='*',
        help='Recipe arguments'
    )

    args = parser.parse_args()

    # Find justfile
    if args.justfile:
        justfile_path = Path(args.justfile)
    else:
        justfile_path = find_justfile()

    if not justfile_path or not justfile_path.exists():
        print("error: No justfile found", file=sys.stderr)
        sys.exit(1)

    # Parse justfile
    with open(justfile_path, 'r') as f:
        content = f.read()

    justfile_parser = Parser(content, str(justfile_path))
    justfile_parser.parse()

    # Process imports
    for imp in justfile_parser.imports:
        import_path = Path(imp.path)
        if not import_path.is_absolute():
            import_path = justfile_path.parent / import_path

        if import_path.exists():
            with open(import_path, 'r') as f:
                import_content = f.read()
            import_parser = Parser(import_content, str(import_path))
            import_parser.parse()

            # Merge imported recipes and assignments
            justfile_parser.recipes.update(import_parser.recipes)
            justfile_parser.assignments.update(import_parser.assignments)
            justfile_parser.aliases.update(import_parser.aliases)
        elif not imp.optional:
            print(f"error: Import file '{imp.path}' not found", file=sys.stderr)
            sys.exit(1)

    # Set working directory
    working_dir = Path(args.working_directory) if args.working_directory else None

    # Create runner
    runner = JustRunner(justfile_parser, working_dir)

    # List recipes
    if args.list:
        runner.list_recipes(args.show_private)
        return

    # Run recipe
    if args.recipe:
        runner.run_recipe(args.recipe, args.args)
    else:
        # Run default recipe if it exists
        if justfile_parser.recipes:
            default_recipe = list(justfile_parser.recipes.keys())[0]
            runner.run_recipe(default_recipe, args.args)
        else:
            print("error: No recipes found", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
