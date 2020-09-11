# c_api_extract.py
Automatic extraction of C APIs from header files using
[Python](http://python.org/) and [clang](https://pypi.org/project/clang/).
Exports struct, union, enum, typedefs, static variables and function definitions
to a JSON file content.


## Usage
Calling from console:

    $ c_api_extract.py [--compact] <input> [-- <clang_args>...]

Or using Python:

```python
import c_api_extract

# `definitions` follow the same format as output JSON
definitions = c_api_extract.definitions_from_header('header_name.h', ['-Dlist_of_clang_args'])
```

`c_api_extract.py` works on a single header file for simplicity.
If you need more than one header processed, create a new one and `#include` them.


## Output format
Output is a list of definitions, each kind with it's format:

```python
# variable definitions
{
  'kind': 'var',
  'name': '<name>',     # variable name
  'type': '<type>'      # type name as written in source code
  'verbatim': '<code>'  # verbatim C code that can be used for variable definition
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
  'verbatim': '<code>'     # verbatim C code that can be used for type definition
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
  'verbatim': '<code>'     # verbatim C code that can be used for type definition
}

# typedef definitions
{
  'kind': 'typedef',
  'name': '<name>',     # name of the typedef
  'type': '<type>',     # name of the underlying type
  'verbatim': '<code>'  # verbatim C code that can be used for type definition
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
  'verbatim': '<code>'       # verbatim C code that can be used for function definition
}
```

## TODO
- Fix variable and function `verbatim` code
- Add support for `#define`d constants
- Add support for nested anonymous struct|unions
