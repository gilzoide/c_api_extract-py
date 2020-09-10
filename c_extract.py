from pprint import pprint
from docopt import docopt
from Visitor import Visitor

doc = """
Usage:
  c_extract.py <input> [<clang_args>...]
"""


def main():
    opts = docopt(doc, options_first=True)
    Visitor().parse_header(opts['<input>'], opts['<clang_args>'])


if __name__ == '__main__':
    main()
