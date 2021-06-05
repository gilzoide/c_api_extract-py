c_api_extract.py
================
Automatic extraction of C APIs from header files using
Python_ and clang_.
Exports struct, union, enum, typedefs, static variables and function definitions
to a JSON file content.

.. _Python: http://python.org/
.. _clang: https://pypi.org/project/clang/


Installing
----------
**c_api_extract** is available on PyPI_ and may be installed using ``pip``::

  $ pip install c-api-extract

.. _PyPI: https://pypi.org/project/c-api-extract/


Usage
-----
Using the command line interface::

    $ c_api_extract <input> [-i <include_pattern>...] [options] [-- <clang_args>...]

Check out the available options with::

    $ c_api_extract -h


Or using Python:

.. code:: python

  import c_api_extract

  # `definitions` follow the same format as output JSON
  definitions = c_api_extract.definitions_from_header('header_name.h', ['-Dsome_clang_args', ...])

**c_api_extract.py** works on a single header file for simplicity.
If you need more than one header processed, create a new one and ``#include`` them.


Output format
-------------
Output is a list of definitions, each kind with its format:

.. code:: python

  # variable definitions
  {
    'kind': 'var',
    'name': '<name>',         # variable name
    'type': <type spelling or object>,  # variable type
    # only present if you pass `--source` to c_api_extract
    'source': '<verbatim definition source code>',
  }

  # constant macro definitions
  {
    'kind': 'const',
    'name': '<name>',
    'type': <type spelling or object>,  # constant type, is always const
  }

  # enum definitions
  {
    'kind': 'enum',
    'name': '<name>',         # enum name, generated for anonymous enums
    'type': <type spelling or object>,  # enum underlying type, usually "unsigned int"
    'values': [               # list of declared names and values
      ['<name>', <integer value>]
      # ...
    ],
    # only present if enum is anonymous
    'anonymous': true,
    # only present if you pass `--source` to c_api_extract
    'source': '<verbatim definition source code>',
  }

  # struct|union definitions
  {
    'kind': 'struct' | 'union',
    'name': '<name>',          # struct|union name, generated for anonymous struct|unions
    'spelling': '<spelling>',  # Spelling that be used directly in C to refer to type
    'fields': [                # list of declared fields, empty for opaque struct|unions
      [<type spelling or object>, '<name>'],  # name may be "" for nested anonymous structs|unions
      ...
    ],
    # only present if record is anonymous
    'anonymous': true,
    # only present if you pass `--source` to c_api_extract
    'source': '<verbatim definition source code>',
  }

  # typedef definitions
  {
    'kind': 'typedef',
    'name': '<name>',         # name of the typedef
    'type': <type spelling or object>,  # underlying type
    # only present if you pass `--source` to c_api_extract
    'source': '<verbatim definition source code>',
  }

  # function definitions
  {
    'kind': 'function',
    'name': '<name>',                # name of the function
    'return_type': <type spelling or object>,  # return type
    'arguments': [                   # list of arguments
      [<type spelling or object>, '<name>'],
      ...
    ],
    # only present if function is variadic
    'variadic': true,
    # only present if you pass `--source` to c_api_extract
    'source': '<verbatim definition source code>',
  }

  #########################################################
  # By default, types are literal strings with the type spelling as provided by clang.
  # If you pass `--type-objects`, a JSON/Dict object is used instead with more detailed
  # information. Its format is described below:
  {
    'base': '<unqualified base type spelling>',
    # only present if type is a pointer type
    'pointer': ['*', ...],
    # only present if type is an array type
    'array': [<integer size>, '<"*" if incomplete array or pointer type>', ...],
    # only present if type is a function pointer type
    'function': {<type object>},
    # only present if type is a function type
    'return_type': {<type object>},
    # only present if type is a function type
    # notice that function types don't carry argument names
    'arguments': [{<type object>}, ...],
    # only present if type is a function type and function is variadic
    'variadic': true,
    # only present if type is a record or enum and record or enum is anonymous
    'anonymous': true,
    # only present if base type is const qualified
    'const': true,
    # only present if base type is volatile qualified
    'volatile': true,
    # only present if base type is restrict qualified
    'restrict': true,
    # only present if you pass `--size` to c_api_extract
    'size': <integer sizeof, may be negative for "void" and incomplete arrays>,
  }


TODO
----
- Add support for constants defined using ``#define``
- Add docstrings
