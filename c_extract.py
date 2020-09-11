from pprint import pprint
from docopt import docopt
from Visitor import Visitor
import Printer

doc = """
Usage:
  c_extract.py <input> [--compact] [<clang_args>...]

Options:
  -c, --compact    Write minified JSON.
"""


def main():
    opts = docopt(doc, options_first=True)
    visitor = Visitor()
    visitor.parse_header(opts['<input>'], opts['<clang_args>'])
    Printer.printVisitor(visitor, opts.get('--compact'))


if __name__ == '__main__':
    main()
