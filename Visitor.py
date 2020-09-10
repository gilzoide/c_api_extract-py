"""AST visitor, using Clang for parsing/understanding of C code and returning
Types in a more useful way to Inclua"""

import Type
import Function

import clang.cindex as clang

from pprint import pprint


class Visitor:
    def __init__(self):
        self.records = set()
        self.enums = {}
        self.functions = set()
        self.index = clang.Index.create()

    def parse_header(self, header_path, clang_args=[]):
        tu = self.index.parse(
            header_path,
            args=clang_args,
            options=clang.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES | clang.TranslationUnit.PARSE_INCOMPLETE | clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )

        visit_queue = list(tu.cursor.get_children())
        self._visit(visit_queue, header_path)
        pprint(self.records)
        pprint(self.enums)
        pprint(self.functions)

    def _visit(self, visit_queue, header_name):
        # headers = set ()
        while visit_queue:
            cursor = visit_queue[0]
            del visit_queue[0]
            if True:  # str (cursor.location.file) == header_name:
                # Typedef: just alias the type
                if cursor.kind == clang.CursorKind.TYPEDEF_DECL:
                    ty = Type.from_cursor(cursor)
                    try:
                        ty.underlying_type.alias = cursor.spelling
                    except:
                        pass
                # Structs/Unions
                elif cursor.kind in [clang.CursorKind.STRUCT_DECL, clang.CursorKind.UNION_DECL]:
                    self.records.add(Type.from_cursor(cursor))
                # Functions
                elif cursor.kind == clang.CursorKind.FUNCTION_DECL:
                    self.functions.add(Function.from_cursor(cursor))
                # Enums
                elif cursor.kind == clang.CursorKind.ENUM_DECL:
                    self.enums[cursor.hash] = Type.from_cursor(cursor)
                elif cursor.kind == clang.CursorKind.ENUM_CONSTANT_DECL:
                    # from pprint import pprint
                    # pprint (self.enums[cursor.semantic_parent.hash])
                    # print (cursor.semantic_parent.hash)
                    self.enums[cursor.semantic_parent.hash].add_value(cursor)
            # nome = str (cursor.location.file)
            # if not nome in headers:
                # print (str (cursor.location.file))
                # headers.add (nome)

            visit_queue.extend(cursor.get_children())
