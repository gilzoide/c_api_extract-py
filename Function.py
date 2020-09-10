"""Function declarations, with it's name, and types (parameters and return)"""

import Type
from Decl import Decl

# Known functions, for memoizing
known_functions = {}


class Function(Decl):
    """Function declaration, with name, and types (parameters and return)"""

    def __init__(self, symbol, ret_type, arguments):
        Decl.__init__(self, symbol)
        self.ret_type = ret_type
        self.arguments = arguments
        self.num_args = len(arguments)

    def __str__(self):
        return self.symbol

    def __repr__(self):
        return 'Function("{}", {}, {})'.format(self.symbol, self.ret_type, self.arguments)

    def return_args_json(self):
        return {
            'return_type': str(self.ret_type),
            'arguments': [(str(arg[0]), str(arg[1])) for arg in self.arguments],
        }

    @staticmethod
    def remember_function(func):
        known_functions[func.symbol] = func
        return func


def from_cursor(cur):
    name = cur.spelling
    memoized = known_functions.get(name)
    if memoized:
        return memoized

    ret_type = Type.from_type(cur.result_type)
    arguments = [(Type.from_type(a.type), a.spelling) for a in cur.get_arguments()]
    return Function.remember_function(Function(name, ret_type, arguments))
