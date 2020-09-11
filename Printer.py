import json
from collections import OrderedDict

def printVisitor(visitor, compact):
    content = OrderedDict(
        enums={ str(e): e.values for e in visitor.enums.values() },
        records={ str(r): r.fields_json() for r in visitor.records },
        functions={ str(f): f.return_args_json() for f in visitor.functions },
    )

    print(json.dumps(content, indent=None if compact else 2))
