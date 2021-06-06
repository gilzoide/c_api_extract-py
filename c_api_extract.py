"""
Usage:
  c_api_extract <input> [-i <include_pattern>...] [options] [-- <clang_args>...]
  c_api_extract -h

General options:
  -h, --help              Show this help message.
  --version               Show the version and exit.

Filtering options:
  -i, --include=<include_pattern>
                          Only process headers with names that match any of the given regex patterns.
                          Matches are tested using `re.search`, so patterns are not anchored by default.
                          This may be used to avoid processing standard headers and dependencies headers.

Output modifier options:
  --compact               Output minified JSON instead of using 2 space indentations.
  --type-objects          Output type objects instead of simply the type spelling string.
  --offset                Include "offset" property with record fields `offsetof` in bytes.
                          Only available with `--type-objects`
  --source                Include declarations' source code verbatim from processed files.
  --size                  Include "size" property with types `sizeof` in bytes.
                          Only available with `--type-objects`
"""

import json
from pathlib import Path, PurePath
import re
from signal import signal, SIGPIPE, SIG_DFL
import subprocess
import tempfile

from docopt import docopt
import clang.cindex as clang


__version__ = '0.6.0'

class CompilationError(Exception):
    pass


class Visitor:
    ANONYMOUS_SUB_RE = re.compile(r'(.*/|\W)')
    UNION_STRUCT_NAME_RE = re.compile(r'(union|struct)\s+(.+)')
    ENUM_NAME_RE = re.compile(r'enum\s+(.+)')
    MATCH_ALL_RE = re.compile('.*')
    DEFINE_RE = re.compile(r'#[ \t]*define[ \t]+([a-zA-Z_][a-zA-Z0-9_]*)[ \t]+')
    BUILTIN_C_DEFINITIONS = {
        "fenv_t", "fexcept_t", "femode_t",  # fenv.h
        "struct lconv",  # locale.h
        "va_list",  # stdarg.h
        "struct atomic_flag",  # stdatomic.h
        "size_t", "ssize_t",  # stddef.h
        "int8_t", "int16_t", "int32_t", "int64_t", "intptr_t",  # stdint.h
        "uint8_t", "uint16_t", "uint32_t", "uint64_t", "uintptr_t",  # stdint.h
        "FILE", "fpos_t",  # stdio.h
        "jmp_buf",  # setjmp.h
        "thrd_t", "mtx_t", "cnd_t",  # threads.h
        "struct tm", "time_t", "struct timespec",  # time.h
    }

    def __init__(self):
        self.defs = []
        self.typedefs = {}
        self.index = clang.Index.create()
        self.types = {}
        self.parsed_headers = set()
        self.potential_constants = []

    def parse_header(self, header_path, clang_args=[], include_patterns=[], type_objects=False,
                     include_source=False, include_size=False, include_offset=False):
        include_patterns = [re.compile(p) for p in include_patterns] or [Visitor.MATCH_ALL_RE]
        tu = self.run_clang(header_path, clang_args)

        self.type_objects = type_objects
        self.include_source = include_source
        self.include_size = include_size
        self.include_offset = include_offset
        self.open_files = {}
        for cursor in tu.cursor.get_children():
            self.process(cursor, include_patterns)
        del self.open_files
        self.process_marked_macros(header_path, clang_args)

    def run_clang(self, header_path, clang_args=[], source=None):
        clang_cmd = ['clang', '-emit-ast', '-o', '-']
        if source:
            clang_cmd.extend(('-x', 'c++', '-'))
        else:
            clang_cmd.append(header_path)
        clang_cmd.extend(clang_args)
        stderr = subprocess.DEVNULL if source else None
        clang_result = subprocess.run(clang_cmd, input=source, stdout=subprocess.PIPE, stderr=stderr)
        if clang_result.returncode != 0:
            raise CompilationError
        with tempfile.NamedTemporaryFile() as ast_file:
            ast_file.write(clang_result.stdout)
            return self.index.read(ast_file.name)

    def source_for_cursor(self, cursor):
        if not self.include_source:
            return None
        source_range = cursor.extent
        start = source_range.start
        end = source_range.end
        filename = (start.file or end.file or cursor.location.file).name
        if filename not in self.open_files:
            self.open_files[filename] = open(filename, 'r')
        f = self.open_files[filename]
        f.seek(start.offset)
        return f.read(end.offset - start.offset)

    def process(self, cursor, include_patterns):
        try:
            cwd = Path.cwd()
            filepath = PurePath(cursor.location.file.name)
            if filepath.is_relative_to(cwd):
                filepath = filepath.relative_to(cwd)
            filepath = str(filepath)
            if not any(pattern.search(filepath) for pattern in include_patterns):
                return
            if filepath not in self.parsed_headers:
                self.mark_macros(filepath)
                self.parsed_headers.add(filepath)
        except AttributeError:
            return

        if cursor.kind == clang.CursorKind.VAR_DECL:
            new_definition = {
                'kind': 'var',
                'name': cursor.spelling,
                'type': self.process_type(cursor.type),
            }
            if self.include_source:
                new_definition['source'] = self.source_for_cursor(cursor)
            self.defs.append(new_definition)
        elif cursor.kind == clang.CursorKind.TYPEDEF_DECL:
            self.process_type(cursor.type)
        elif cursor.kind == clang.CursorKind.ENUM_DECL:
            self.process_type(cursor.type)
        elif cursor.kind == clang.CursorKind.STRUCT_DECL:
            self.process_type(cursor.type)
        elif cursor.kind == clang.CursorKind.UNION_DECL:
            self.process_type(cursor.type)
        elif cursor.kind == clang.CursorKind.FUNCTION_DECL:
            new_definition = {
                'kind': 'function',
                'name': cursor.spelling,
                'return_type': self.process_type(cursor.type.get_result()),
                'arguments': [(self.process_type(a.type), a.spelling)
                              for a in cursor.get_arguments()],
            }
            if cursor.type.kind == clang.TypeKind.FUNCTIONPROTO and cursor.type.is_function_variadic():
                new_definition['variadic'] = True
            if self.include_source:
                new_definition['source'] = self.source_for_cursor(cursor)
            self.defs.append(new_definition)

    def process_type(self, t):
        if t.kind == clang.TypeKind.ELABORATED:
            # just process inner type
            t = t.get_named_type()
        declaration = t.get_declaration()
        # print('processing ', t.kind, t.spelling)
        base = t
        spelling = t.spelling
        result = {}
        if t.kind == clang.TypeKind.RECORD and spelling not in self.BUILTIN_C_DEFINITIONS:
            m = self.UNION_STRUCT_NAME_RE.match(spelling)
            if m:
                union_or_struct = m.group(1)
                anonymous = self.ANONYMOUS_SUB_RE.search(m.group(2))
                name = self.ANONYMOUS_SUB_RE.sub('_', m.group(2))
                spelling = '{} {}'.format(union_or_struct, name)
            else:
                assert declaration.kind in (clang.CursorKind.STRUCT_DECL, clang.CursorKind.UNION_DECL)
                union_or_struct = ('struct'
                                   if declaration.kind == clang.CursorKind.STRUCT_DECL
                                   else 'union')
                anonymous = False
                name = t.spelling
            if declaration.hash not in self.types:
                self.types[declaration.hash] = spelling
                fields = []
                for field in t.get_fields():
                    new_field = [
                        self.process_type(field.type),
                        field.spelling,
                    ]
                    if self.include_offset:
                        new_field.append(field.get_field_offsetof())
                    fields.append(new_field)
                new_definition = {
                    'kind': union_or_struct,
                    'fields': fields,
                    'name': name,
                    'spelling': spelling,
                }
                if anonymous:
                    new_definition['anonymous'] = True
                if self.include_source:
                    new_definition['source'] = self.source_for_cursor(declaration)
                if self.include_size:
                    new_definition['size'] = t.get_size()
                self.defs.append(new_definition)
        elif t.kind == clang.TypeKind.ENUM:
            if declaration.hash not in self.types:
                self.types[declaration.hash] = spelling
                m = self.ENUM_NAME_RE.match(t.spelling)
                if m:
                    anonymous = self.ANONYMOUS_SUB_RE.search(m.group(1))
                    name = self.ANONYMOUS_SUB_RE.sub('_', m.group(1))
                    spelling = "enum {}".format(name)
                else:
                    anonymous = False
                    name = t.spelling
                new_definition = {
                    'kind': 'enum',
                    'name': name,
                    'spelling': spelling,
                    'type': self.process_type(declaration.enum_type),
                    'values': [(c.spelling, c.enum_value) for c in declaration.get_children()],
                }
                if anonymous:
                    new_definition['anonymous'] = True
                if self.include_source:
                    new_definition['source'] = self.source_for_cursor(declaration)
                self.defs.append(new_definition)
        elif t.kind == clang.TypeKind.TYPEDEF and spelling not in self.BUILTIN_C_DEFINITIONS:
            if declaration.hash not in self.types:
                self.types[declaration.hash] = spelling
                new_definition = {
                    'kind': 'typedef',
                    'name': t.get_typedef_name(),
                    'type': self.process_type(declaration.underlying_typedef_type),
                }
                if self.include_source:
                    new_definition['source'] = self.source_for_cursor(declaration)
                self.defs.append(new_definition)
        elif t.kind == clang.TypeKind.POINTER:
            result['pointer'], base = self.process_pointer_or_array(t)
            pointer_base = self.process_type(base)
            base_spelling = pointer_base['spelling'] if self.type_objects else pointer_base
            spelling = spelling.replace(base.spelling, base_spelling)
            if base.kind in (clang.TypeKind.FUNCTIONPROTO, clang.TypeKind.FUNCTIONNOPROTO):
                result['function'] = pointer_base
        elif t.kind in (clang.TypeKind.CONSTANTARRAY, clang.TypeKind.INCOMPLETEARRAY):
            result['array'], base = self.process_pointer_or_array(t)
            array_base = self.process_type(base)
            base_spelling = array_base['spelling'] if self.type_objects else array_base
            spelling = spelling.replace(base.spelling, base_spelling)
        elif t.kind in (clang.TypeKind.FUNCTIONPROTO, clang.TypeKind.FUNCTIONNOPROTO):
            result['return_type'] = self.process_type(t.get_result())
            result['arguments'] = [self.process_type(a)
                                   for a in t.argument_types()],
            if t.kind == clang.TypeKind.FUNCTIONPROTO and t.is_function_variadic():
                result['variadic'] = True
        else:
            # print('WHAT? ', t.kind, spelling)
            pass
        if not self.type_objects:
            return spelling
        if base.is_const_qualified():
            result['const'] = True
        if base.is_volatile_qualified():
            result['volatile'] = True
        if base.is_restrict_qualified():
            result['restrict'] = True
        result['spelling'] = spelling
        result['base'] = base_type(base.spelling if base is not t else spelling)
        if self.include_size:
            result['size'] = t.get_size()

        return result

    @classmethod
    def process_pointer_or_array(cls, t):
        result = []
        while t:
            if t.kind == clang.TypeKind.POINTER:
                result.append('*')
                t = t.get_pointee()
            elif t.kind == clang.TypeKind.CONSTANTARRAY:
                result.append(t.get_array_size())
                t = t.element_type
            elif t.kind == clang.TypeKind.INCOMPLETEARRAY:
                result.append('*')
                t = t.element_type
            else:
                break
        return result, t

    def mark_macros(self, filepath):
        with open(filepath) as f:
            for line in f:
                m = self.DEFINE_RE.match(line)
                if m:
                    self.potential_constants.append(m.group(1))

    def process_marked_macros(self, header_path, clang_args=[]):
        for identifier in self.potential_constants:
            try:
                source = '#include "{}"\nconst auto __value = {};'.format(header_path, identifier)
                tu = self.run_clang(header_path, clang_args, source.encode('utf-8'))
                for cursor in tu.cursor.get_children():
                    if cursor.kind == clang.CursorKind.VAR_DECL and cursor.spelling == '__value':
                        new_definition = {
                            'kind': 'const',
                            'name': identifier,
                            'type': self.process_type(cursor.type),
                        }
                        self.defs.append(new_definition)
            except CompilationError:
                # this macro is not a const value, skip
                pass


TYPE_COMPONENTS_RE = re.compile(r'([^(]*\(\**|[^[]*)(.*)')
def typed_declaration(spelling, identifier):
    """
    Utility to form a typed declaration from a C type and identifier.
    This correctly handles array lengths and function pointer arguments.
    """
    m = TYPE_COMPONENTS_RE.match(spelling)
    return '{base_or_return_type}{maybe_space}{identifier}{maybe_array_or_arguments}'.format(
        base_or_return_type=m.group(1),
        maybe_space='' if m.group(2) else ' ',
        identifier=identifier,
        maybe_array_or_arguments=m.group(2) or '',
    )


BASE_TYPE_RE = re.compile(r'(?:\b(?:const|volatile|restrict)\b\s*)*(([^[*(]+)(\(?).*)')
def base_type(spelling):
    """
    Get the base type from spelling, removing const/volatile/restrict specifiers and pointers.
    """
    m = BASE_TYPE_RE.match(spelling)
    return (m.group(1) if m.group(3) else m.group(2)).strip()


def definitions_from_header(*args, **kwargs):
    visitor = Visitor()
    visitor.parse_header(*args, **kwargs)
    return visitor.defs


def main():
    opts = docopt(__doc__, version=__version__)
    try:
        definitions = definitions_from_header(opts['<input>'],
                                              clang_args=opts['<clang_args>'],
                                              include_patterns=opts['--include'],
                                              type_objects=opts['--type-objects'],
                                              include_source=opts['--source'],
                                              include_size=opts['--size'],
                                              include_offset=opts['--offset'])
        signal(SIGPIPE, SIG_DFL)
        compact = opts.get('--compact')
        print(json.dumps(definitions, indent=None if compact else 2, separators=(',', ':') if compact else None), end='')
    except CompilationError as e:
        # clang have already dumped its errors to stderr
        pass


if __name__ == '__main__':
    main()
