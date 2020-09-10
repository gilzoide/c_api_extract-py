from pprint import pprint
from docopt import docopt
from Visitor import Visitor
import Printer

doc = """
Usage:
  c_extract.py <input> [-b <base_path>] [<clang_args>...]

Options:
  -b <base_path>, --base <base_path>    Base path were 
"""


def main():
    opts = docopt(doc, options_first=True)
    visitor = Visitor()
    visitor.parse_header(opts['<input>'], opts['<clang_args>'])
    Printer.printVisitor(visitor)


if __name__ == '__main__':
    main()
