"""Compare method/path contracts directly with the original Java controllers."""
import json
from pathlib import Path
import re
from bemodel.main import create_app

root = Path(__file__).resolve().parents[2]
expected = set()
for source in (root / 'bemodel-server/src/main/java').rglob('*.java'):
    java = source.read_text(encoding='utf-8')
    if '@RestController' not in java:
        continue
    prefix = re.search(r'@RequestMapping\("([^"]+)"\)', java)
    prefix = prefix.group(1) if prefix else ''
    for match in re.finditer(r'@(Get|Post|Put|Delete|Patch)Mapping(?:\("([^"]*)"\))?', java):
        expected.add((match.group(1).upper(), prefix+(match.group(2) or '')))


def normalize(route):
    method, path = route
    return method, re.sub(r'\{[^}]+\}', '{}', path).rstrip('/')


actual = {(method, r.path) for r in create_app(startup=False).routes if r.path.startswith('/api') for method in r.methods}
missing = sorted(r for r in expected if normalize(r) not in {normalize(a) for a in actual})
extra = sorted(r for r in actual if normalize(r) not in {normalize(e) for e in expected})
report = dict(javaCount=len(expected), pythonCount=len(actual), missing=missing, extra=extra, javaRoutes=sorted(expected), pythonRoutes=sorted(actual))
destination = root / 'bemodel-server-py/artifacts/routes.json'
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if not k.endswith('Routes')}, ensure_ascii=False))
raise SystemExit(bool(missing or extra))
