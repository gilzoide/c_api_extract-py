# c_api_extract.py
Automatic extraction of C APIs from header files using
[Python](http://python.org/) and [clang](https://pypi.org/project/clang/).
Exports struct/union/enum, typedefs, static variables and function definitions
to a JSON file content.

## Usage
Calling from console:

    $ c_api_extract.py [--compact] <input> [-- <clang_args>...]

Or using Python:

```python
import c_api_extract

definitions = c_api_extract.definitions_from_header('header_name.h', ['-Dclang_args'])
# definitions follow the same format as output JSON
```

`c_extract.py` works on a single header file for simplicity.
If you need more than one header processed, create a new one and `#include` them.

