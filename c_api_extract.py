"""
Usage:
  c_api_extract.py [--compact] <input> [-- <clang_args>...]
  c_api_extract.py -h

Options:
  -c, --compact    Write minified JSON.
  -h, --help       Show this help message.
"""

import json

from docopt import docopt
import clang.cindex as clang


def verbatim_code(cursor):
    return ' '.join(t.spelling for t in cursor.get_tokens() if not t.spelling.startswith('/'))


class Visitor:
    def __init__(self):
        self.defs = []
        self.typedefs = {}
        self.index = clang.Index.create()

    def parse_header(self, header_path, clang_args=[]):
        tu = self.index.parse(
            header_path,
            args=clang_args,
            options=clang.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES | clang.TranslationUnit.PARSE_INCOMPLETE | clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )
        for cursor in tu.cursor.get_children():
            self.process(cursor)

    def add_typedef(self, cursor, ty):
        self.typedefs[cursor.hash] = ty

    def get_typedef(self, cursor):
        return self.typedefs.get(cursor.underlying_typedef_type.get_declaration().hash)

    def process(self, cursor):
        if cursor.kind == clang.CursorKind.VAR_DECL:
            self.defs.append(dict(
                kind='var',
                name=cursor.spelling,
                type=cursor.type.spelling,
                verbatim=verbatim_code(cursor),
            ))
        elif cursor.kind == clang.CursorKind.TYPEDEF_DECL:
            definition = self.get_typedef(cursor)
            if definition:
                definition['typedef'] = cursor.spelling

            self.defs.append(dict(
                kind='typedef',
                name=cursor.spelling,
                type=cursor.underlying_typedef_type.spelling,
                verbatim=verbatim_code(cursor),
            ))
        elif cursor.kind == clang.CursorKind.ENUM_DECL:
            enum = dict(
                kind='enum',
                name=cursor.spelling,
                type=cursor.enum_type.spelling,
                values=[(c.spelling, c.enum_value)
                        for c in cursor.get_children()],
                verbatim=verbatim_code(cursor),
            )
            self.defs.append(enum)
            self.add_typedef(cursor, enum)
        elif cursor.kind == clang.CursorKind.STRUCT_DECL:
            struct = dict(
                kind='struct',
                name=cursor.spelling,
                fields=[(f.type.spelling, f.spelling)
                        for f in cursor.type.get_fields()],
                verbatim=verbatim_code(cursor),
            )
            self.defs.append(struct)
            self.add_typedef(cursor, struct)
        elif cursor.kind == clang.CursorKind.UNION_DECL:
            union = dict(
                kind='union',
                name=cursor.spelling,
                fields=[(f.type.spelling, f.spelling)
                        for f in cursor.type.get_fields()],
                verbatim=verbatim_code(cursor),
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
                verbatim=verbatim_code(cursor),
            )
            self.defs.append(function)


def definitions_from_header(*args, **kwargs):
    visitor = Visitor()
    visitor.parse_header(*args, **kwargs)
    return visitor.defs


def main():
    opts = docopt(__doc__)
    definitions = definitions_from_header(
        opts['<input>'], opts['<clang_args>'])
    print(json.dumps(definitions, indent=None if opts.get('--compact') else 2))


if __name__ == '__main__':
    main()
