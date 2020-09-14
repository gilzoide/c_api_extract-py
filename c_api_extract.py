"""
Usage:
  c_api_extract <input> [-p <pattern>...] [-c] [-- <clang_args>...]
  c_api_extract -h

Options:
  -c, --compact                        Write minified JSON.
  -h, --help                           Show this help message.
  -p <pattern>, --pattern=<pattern>    Only process headers with names that match any of the given regex patterns.
                                       Matches are tested using `re.search`, so patterns are not anchored by default.
                                       This may be used to avoid processing standard headers and dependencies headers.
"""

import json
import re
from signal import signal, SIGPIPE, SIG_DFL

from docopt import docopt
import clang.cindex as clang


__version__ = '0.4.0'

class Visitor:
    def __init__(self):
        self.defs = []
        self.typedefs = {}
        self.index = clang.Index.create()

    match_all_re = re.compile('.*')
    def parse_header(self, header_path, clang_args=[], allowed_patterns=[]):
        allowed_patterns = [re.compile(p) for p in allowed_patterns] or [Visitor.match_all_re]
        tu = self.index.parse(
            header_path,
            args=clang_args,
            options=clang.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES | clang.TranslationUnit.PARSE_INCOMPLETE | clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )
        self.open_files = {}
        for cursor in tu.cursor.get_children():
            self.process(cursor, allowed_patterns)
        del self.open_files

    def add_typedef(self, cursor, ty):
        self.typedefs[cursor.hash] = ty

    def get_typedef(self, cursor):
        return self.typedefs.get(cursor.underlying_typedef_type.get_declaration().hash)

    def source_for_cursor(self, cursor):
        source_range = cursor.extent
        start = source_range.start
        end = source_range.end
        filename = (start.file or end.file or cursor.location.file).name
        if filename not in self.open_files:
            self.open_files[filename] = open(filename, 'r')
        f = self.open_files[filename]
        f.seek(start.offset)
        return f.read(end.offset - start.offset)

    def process(self, cursor, allowed_patterns):
        try:
            filename = cursor.location.file.name
            if not any(pattern.search(filename) for pattern in allowed_patterns):
                return
        except AttributeError:
            return

        if cursor.kind == clang.CursorKind.VAR_DECL:
            self.defs.append(dict(
                kind='var',
                name=cursor.spelling,
                type=cursor.type.spelling,
                source=self.source_for_cursor(cursor),
            ))
        elif cursor.kind == clang.CursorKind.TYPEDEF_DECL:
            definition = self.get_typedef(cursor)
            if definition:
                definition['typedef'] = cursor.spelling

            self.defs.append(dict(
                kind='typedef',
                name=cursor.spelling,
                type=cursor.underlying_typedef_type.spelling,
                source=self.source_for_cursor(cursor),
            ))
        elif cursor.kind == clang.CursorKind.ENUM_DECL:
            enum = dict(
                kind='enum',
                name=cursor.spelling,
                type=cursor.enum_type.spelling,
                values=[(c.spelling, c.enum_value)
                        for c in cursor.get_children()],
                source=self.source_for_cursor(cursor),
            )
            self.defs.append(enum)
            self.add_typedef(cursor, enum)
        elif cursor.kind == clang.CursorKind.STRUCT_DECL:
            struct = dict(
                kind='struct',
                name=cursor.spelling,
                fields=[(f.type.spelling, f.spelling)
                        for f in cursor.type.get_fields()],
                source=self.source_for_cursor(cursor),
            )
            self.defs.append(struct)
            self.add_typedef(cursor, struct)
        elif cursor.kind == clang.CursorKind.UNION_DECL:
            union = dict(
                kind='union',
                name=cursor.spelling,
                fields=[(f.type.spelling, f.spelling)
                        for f in cursor.type.get_fields()],
                source=self.source_for_cursor(cursor),
            )
            self.defs.append(union)
            self.add_typedef(cursor, union)
        elif cursor.kind == clang.CursorKind.FUNCTION_DECL:
            function = dict(
                kind='function',
                name=cursor.spelling,
                return_type=cursor.type.get_result().spelling,
                arguments=[(a.type.spelling, a.spelling)
                           for a in cursor.get_arguments()],
                variadic=cursor.type.kind == clang.TypeKind.FUNCTIONPROTO and cursor.type.is_function_variadic(),
                source=self.source_for_cursor(cursor),
            )
            self.defs.append(function)

type_components_re = re.compile(r'([^[*]*\**)(.*)')
def typed_declaration(ty, identifier):
    """
    Utility to form a typed declaration from a C type and identifier.
    This correctly handles array lengths and function pointer arguments.
    """
    m = type_components_re.match(ty)
    return '{base_or_return_type}{maybe_space}{identifier}{maybe_array_or_arguments}'.format(
        base_or_return_type=m.group(1),
        maybe_space='' if m.group(2) else ' ',
        identifier=identifier,
        maybe_array_or_arguments=m.group(2) or '',
    )

base_type_re = re.compile(r'(?:\b(?:const|volatile|restrict)\b\s*)*(([^[*(]+)(\(?).*)')
def base_type(ty):
    """
    Get the base type from spelling, removing const/volatile/restrict specifiers and pointers.
    """
    m = base_type_re.match(ty)
    return (m.group(1) if m.group(3) else m.group(2)).strip()

def definitions_from_header(*args, **kwargs):
    visitor = Visitor()
    visitor.parse_header(*args, **kwargs)
    return visitor.defs


def main():
    opts = docopt(__doc__)
    definitions = definitions_from_header(
        opts['<input>'], opts['<clang_args>'], opts['--pattern'])
    signal(SIGPIPE, SIG_DFL)
    print(json.dumps(definitions, indent=None if opts.get('--compact') else 2))


if __name__ == '__main__':
    main()
