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

from collections import OrderedDict
import json
from pathlib import Path, PurePath
import re
from signal import signal, SIGPIPE, SIG_DFL
import subprocess
import tempfile

from docopt import docopt
import clang.cindex as clang


__version__ = '0.7.0'

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

class CompilationError(Exception):
    pass


class Definition:
    def __init__(self, kind):
        self.kind = kind

    def to_dict(self, is_declaration=True):
        return {
            'kind': self.kind,
        }

    def is_record(self):
        return self.kind in ('struct', 'union')


class Type(Definition):
    known_types = OrderedDict()

    class Field:
        def __init__(self, field_cursor):
            self.name = field_cursor.spelling
            self.type = Type.from_clang(field_cursor.type)

        def to_dict(self):
            return {
                'name': self.name,
                'type': self.type.to_dict(),
            }

    class EnumValue:
        def __init__(self, name, value):
            self.name = name
            self.value = value

        def to_dict(self):
            return {
                'name': self.name,
                'value': self.value,
            }

    def __init__(self, t):
        super().__init__('')
        self.clang_kind = t.kind
        self.spelling = t.spelling
        declaration = t.get_declaration()
        base = t
        if t.kind == clang.TypeKind.RECORD and t.spelling not in BUILTIN_C_DEFINITIONS:
            m = UNION_STRUCT_NAME_RE.match(t.spelling)
            if m:
                union_or_struct = m.group(1)
                self.anonymous = bool(ANONYMOUS_SUB_RE.search(m.group(2)))
                self.name = ANONYMOUS_SUB_RE.sub('_', m.group(2))
                self.spelling = '{} {}'.format(union_or_struct, self.name)
            else:
                assert declaration.kind in (clang.CursorKind.STRUCT_DECL, clang.CursorKind.UNION_DECL)
                union_or_struct = ('struct'
                                   if declaration.kind == clang.CursorKind.STRUCT_DECL
                                   else 'union')
                self.anonymous = False
                self.name = t.spelling
            self.kind = union_or_struct
            self.fields = [Type.Field(f) for f in t.get_fields()]
            self.opaque = not self.fields
        elif t.kind == clang.TypeKind.ENUM:
            m = ENUM_NAME_RE.match(t.spelling)
            if m:
                self.anonymous = bool(ANONYMOUS_SUB_RE.search(m.group(1)))
                self.name = ANONYMOUS_SUB_RE.sub('_', m.group(1))
                self.spelling = "enum {}".format(self.name)
            else:
                self.anonymous = False
                self.name = t.spelling
            self.kind = 'enum'
            self.type = Type.from_clang(declaration.enum_type)
            self.values = [Type.EnumValue(c.spelling, c.enum_value) for c in declaration.get_children()]
        elif t.kind == clang.TypeKind.TYPEDEF and t.spelling not in BUILTIN_C_DEFINITIONS:
            self.kind = 'typedef'
            self.name = t.get_typedef_name()
            self.type = Type.from_clang(declaration.underlying_typedef_type)
        elif t.kind == clang.TypeKind.POINTER:
            self.kind = 'pointer'
            self.array, base = self.process_pointer_or_array(t)
            self.element_type = Type.from_clang(base)
            self.spelling = self.spelling.replace(base.spelling, self.element_type.spelling)
            if base.kind in (clang.TypeKind.FUNCTIONPROTO, clang.TypeKind.FUNCTIONNOPROTO):
                self.function = self.element_type
        elif t.kind in (clang.TypeKind.CONSTANTARRAY, clang.TypeKind.INCOMPLETEARRAY):
            self.kind = 'array'
            self.array, base = self.process_pointer_or_array(t)
            self.element_type = Type.from_clang(base)
            self.spelling = self.spelling.replace(base.spelling, self.element_type.spelling)
        elif t.kind in (clang.TypeKind.FUNCTIONPROTO, clang.TypeKind.FUNCTIONNOPROTO):
            self.kind = 'function'
            self.return_type = Type.from_clang(t.get_result())
            self.arguments = [Type.from_clang(a) for a in t.argument_types()]
            self.variadic = t.kind == clang.TypeKind.FUNCTIONPROTO and t.is_function_variadic()
        elif t.kind == clang.TypeKind.VOID:
            self.kind = 'void'
        elif t.kind == clang.TypeKind.BOOL:
            self.kind = 'bool'
        elif t.kind in (clang.TypeKind.CHAR_U, clang.TypeKind.UCHAR, clang.TypeKind.CHAR16, clang.TypeKind.CHAR32, clang.TypeKind.CHAR_S, clang.TypeKind.SCHAR, clang.TypeKind.WCHAR):
            self.kind = 'char'
        elif t.kind in (clang.TypeKind.USHORT, clang.TypeKind.UINT, clang.TypeKind.ULONG, clang.TypeKind.ULONGLONG, clang.TypeKind.UINT128):
            self.kind = 'uint'
        elif t.kind in (clang.TypeKind.SHORT, clang.TypeKind.INT, clang.TypeKind.LONG, clang.TypeKind.LONGLONG, clang.TypeKind.INT128):
            self.kind = 'int'
        elif t.kind in (clang.TypeKind.FLOAT, clang.TypeKind.DOUBLE, clang.TypeKind.LONGDOUBLE, clang.TypeKind.HALF, clang.TypeKind.FLOAT128):
            self.kind = 'float'
        else:
            assert t.kind != clang.TypeKind.INVALID, "FIXME: invalid type"

        self.const = base.is_const_qualified()
        self.volatile = base.is_volatile_qualified()
        self.restrict = base.is_restrict_qualified()
        self.base = base_type(base.spelling if base is not t else self.spelling)
        self.size = t.get_size()

    def root(self):
        t = self
        while t.kind == 'typedef':
            t = t.type
        return t

    def is_primitive(self):
        return self.kind not in ('typedef', 'enum', 'struct', 'union')

    def is_integral(self):
        return self.kind in ('uint', 'int')

    def is_unsigned(self):
        return self.kind == 'uint'

    def is_floating_point(self):
        return self.kind == 'float'

    def is_string(self):
        return self.kind == 'pointer' and len(self.array) == 1 and self.element_type.kind == 'char'

    def is_pointer(self):
        return self.kind == 'pointer'

    def is_function_pointer(self):
        return self.kind == 'pointer' and hasattr(self, 'function')

    def is_variadic(self):
        return getattr(self, 'variadic', False)

    def is_anonymous(self):
        return getattr(self, 'anonymous', False)

    def is_string_array(self):
        return self.kind == 'pointer' and len(self.array) >= 1 and self.element_type.kind == 'char'

    def to_dict(self, is_declaration=False):
        result = {
            'kind': self.kind,
            'spelling': self.spelling,
            'size': self.size,
        }
        if is_declaration:
            if hasattr(self, 'fields'):
                result['fields'] = [f.to_dict() for f in self.fields]
            if hasattr(self, 'values'):
                result['values'] = [v.to_dict() for v in self.values]
        else:
            result['base'] = self.base
        if hasattr(self, 'name'):
            result['name'] = self.name
        if hasattr(self, 'type'):
            result['type'] = self.type.to_dict()
        if hasattr(self, 'function'):
            result['function'] = self.function.to_dict()
        if hasattr(self, 'return_type'):
            result['return_type'] = self.return_type.to_dict()
        if hasattr(self, 'arguments'):
            result['arguments'] = [a.to_dict() for a in self.arguments]
        if self.is_anonymous():
            result['anonymous'] = True
        if self.is_variadic():
            result['variadic'] = True
        if self.const:
            result['const'] = True
        if self.volatile:
            result['volatile'] = True
        if self.restrict:
            result['restrict'] = True
        return result

    @classmethod
    def from_clang(cls, t):
        if t.kind == clang.TypeKind.AUTO:
            # process actual type
            t = t.get_canonical()
        if t.kind == clang.TypeKind.ELABORATED:
            # just process inner type
            t = t.get_named_type()
        declaration = t.get_declaration()
        the_type = cls.known_types.get(declaration.hash)
        if not the_type:
            the_type = Type(t)
            if not the_type.is_primitive():
                cls.known_types[declaration.hash] = the_type
        return the_type

    @staticmethod
    def process_pointer_or_array(t):
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


class Variable(Definition):
    def __init__(self, cursor):
        super().__init__('var')
        self.name = cursor.spelling
        self.type = Type.from_clang(cursor.type)

    def to_dict(self, is_declaration=True):
        return {
            'kind': self.kind,
            'name': self.name,
            'type': self.type.to_dict(),
        }


class Constant(Definition):
    def __init__(self, cursor, name):
        super().__init__('const')
        self.name = name
        self.type = Type.from_clang(cursor.type)

    def to_dict(self, is_declaration=True):
        return {
            'kind': self.kind,
            'name': self.name,
            'type': self.type.to_dict(),
        }


class Function(Definition):
    class Argument:
        def __init__(self, cursor):
            self.name = cursor.spelling
            self.type = Type.from_clang(cursor.type)

        def to_dict(self):
            return {
                'name': self.name,
                'type': self.type.to_dict(),
            }

    def __init__(self, cursor):
        super().__init__('function')
        self.name = cursor.spelling
        self.return_type = Type.from_clang(cursor.type.get_result())
        self.arguments = [Function.Argument(a) for a in cursor.get_arguments()]
        self.variadic = cursor.type.kind == clang.TypeKind.FUNCTIONPROTO and cursor.type.is_function_variadic()

    def to_dict(self, is_declaration=True):
        d = {
            'kind': self.kind,
            'name': self.name,
            'return_type': self.return_type.to_dict(),
            'arguments': [a.to_dict() for a in self.arguments]
        }
        if self.variadic:
            d['variadic'] = True
        return d


class Visitor:
    def __init__(self):
        self.defs = []
        self.typedefs = {}
        self.index = clang.Index.create()
        self.parsed_headers = set()
        self.potential_constants = []

    def parse_header(self, header_path, clang_args=[], include_patterns=[], type_objects=False,
                     include_source=False, include_size=False, include_offset=False):
        include_patterns = [re.compile(p) for p in include_patterns] or [MATCH_ALL_RE]
        tu = self.run_clang(header_path, clang_args)

        self.type_objects = type_objects
        self.include_source = include_source
        self.include_size = include_size
        self.include_offset = include_offset
        for cursor in tu.cursor.get_children():
            self.process(cursor, include_patterns)
        type_defs = [t for t in Type.known_types.values()]
        self.defs = type_defs + self.defs
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
            new_definition = Variable(cursor)
            self.defs.append(new_definition)
        if cursor.kind in (clang.CursorKind.TYPEDEF_DECL, clang.CursorKind.ENUM_DECL, clang.CursorKind.STRUCT_DECL, clang.CursorKind.UNION_DECL):
            self.process_type(cursor.type)
        elif cursor.kind == clang.CursorKind.FUNCTION_DECL:
            self.defs.append(Function(cursor))

    def process_type(self, t):
        new_declaration = Type.from_clang(t)


    def mark_macros(self, filepath):
        with open(filepath) as f:
            for line in f:
                m = DEFINE_RE.match(line)
                if m:
                    self.potential_constants.append(m.group(1))

    def process_marked_macros(self, header_path, clang_args=[]):
        for identifier in self.potential_constants:
            try:
                source = '#include "{}"\nconst auto __value = {};'.format(header_path, identifier)
                tu = self.run_clang(header_path, clang_args, source.encode('utf-8'))
                for cursor in tu.cursor.get_children():
                    if cursor.kind == clang.CursorKind.VAR_DECL and cursor.spelling == '__value':
                        self.defs.append(Constant(cursor, identifier))
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
    if not m:
        print("FIXME: ", spelling)
    return (m.group(1) if m.group(3) else m.group(2)).strip() if m else spelling


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
        print(json.dumps([d.to_dict(is_declaration=True) for d in definitions],
                         indent=None if compact else 2,
                         separators=(',', ':') if compact else None),
              end='')
    except CompilationError as e:
        # clang have already dumped its errors to stderr
        pass


if __name__ == '__main__':
    main()
