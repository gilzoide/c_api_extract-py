c_api_extract.py
================
Automatic extraction of C APIs from header files using
Python_ and clang_.
Exports struct, union, enum, typedefs, static variables and function definitions
to a JSON file content.

.. _Python: http://python.org/
.. _clang: https://pypi.org/project/clang/


Usage
-----
Calling from console::

    $ c_api_extract.py <input> [-p <pattern>...] [-c] [-- <clang_args>...]


Or using Python:

.. code:: python

  import c_api_extract

  # `definitions` follow the same format as output JSON
  definitions = c_api_extract.definitions_from_header('header_name.h', ['-I/usr/lib/clang/<version>/include', '-Dother_clang_args', ...])

`c_api_extract.py` works on a single header file for simplicity.
If you need more than one header processed, create a new one and `#include` them.

It is recommended to pass `-I<path to clang headers>` to *clang* to correctly include some
standard headers like **stddef.h** and **stdbool.h**.


Output format
-------------
Output is a list of definitions, each kind with it's format:

.. code:: python

  # variable definitions
  {
    'kind': 'var',
    'name': '<name>',   # variable name
    'type': '<type>'    # type name as written in source code
    'source': '<code>'  # source C code from read header file
  }

  # enum definitions
  {
    'kind': 'enum',
    'name': '<name>',        # enum name, empty for anonymous enums
    'typedef': '<typedef>',  # typedef name, may be empty
    'type': '<C type>',      # enum underlying C type name
    'values': [              # list of declared names and values
      ['<name>', <integer value>]
      # ...
    ],
    'source': '<code>'       # source C code from read header file
  }

  # struct|union definitions
  {
    'kind': 'struct' | 'union',
    'name': '<name>',        # struct|union name, empty for anonymous struct|unions
    'typedef': '<typedef>',  # typedef name, may be empty
    'fields': [              # list of declared fields, empty for opaque struct|unions
      ['<type>', '<name>']
      # ...
    ],
    'source': '<code>'       # source C code from read header file
  }

  # typedef definitions
  {
    'kind': 'typedef',
    'name': '<name>',   # name of the typedef
    'type': '<type>',   # name of the underlying type
    'source': '<code>'  # source C code from read header file
  }

  # function definitions
  {
    'kind': 'function',
    'name': '<name>',          # name of the function
    'return_type': '<type>',   # return type name
    'arguments': [             # list of arguments
      ['<type>', '<name>']
      # ...
    ],
    'variadic': true | false,  # true if function is variadic
    'source': '<code>'         # source C code from read header file
  }


TODO
----
- Include *clang* standard headers by default based on host operating system
- Add support for constants defined using `#define` 
- Add support for nested anonymous struct|unions
- Add docstrings
