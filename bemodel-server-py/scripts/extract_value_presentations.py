"""Translate the four static presentation expressions, preserving their wording."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'bemodel-server/src/main/java/com/bemodel/value/ValueService.java').read_text(encoding='utf-8')


class Expression:
    def __init__(self, text):
        self.tokens = re.findall(r'"(?:\\.|[^"\\])*"|[A-Za-z_][A-Za-z_0-9]*|[().,+;]', text)
        self.pos = 0

    def pop(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def atom(self):
        token = self.pop()
        if token.startswith('"'):
            return repr(json.loads(token))
        value = token
        while self.tokens[self.pos] in ('.', '('):
            if self.tokens[self.pos] == '.':
                self.pop()
                method = self.pop()
                value += '.'+({'getOrDefault': 'get', 'size': '__len__'}.get(method, method))
            else:
                self.pop()
                args = []
                while self.tokens[self.pos] != ')':
                    args.append(self.expression())
                    if self.tokens[self.pos] == ',':
                        self.pop()
                    else:
                        break
                assert self.pop() == ')'
                value = ('list_of' if value == 'List.of' else value)+'('+', '.join(args)+')'
        return value

    def expression(self):
        parts = [self.atom()]
        while self.tokens[self.pos] == '+':
            self.pop()
            parts.append(self.atom())
        return parts[0] if len(parts) == 1 else 'concat('+', '.join(parts)+')'


output = '''# Generated presentation expressions; all probes live in services.py.
def concat(*values):
    return ''.join('null' if v is None else str(v) for v in values)

def list_of(*values):
    return list(values)

def experiment(key, title, question, a, b, c, verdict):
    return dict(key=key, title=title, question=question, a=a, b=b, c=c, verdict=verdict)

def side(label, tag, outcome, lines, basis):
    return dict(label=label, tag=tag, outcome=outcome, lines=lines, basis=basis)

'''
for method, name, args in [('expGate', 'gate', 'hit, trace'), ('expSilo', 'silo', 'impact, dict, adapterHasC'), ('expAdversarial', 'adversarial', 'actions, m1'), ('expTraverse', 'traverse', 'staff, dept, footprint, colleagues')]:
    chunk = source.split('private Map<String, Object> '+method+'()')[1]
    expression = 'experiment('+chunk.split('return experiment(', 1)[1].split(';', 1)[0]+';'
    output += f'def {name}({args}):\n    return '+Expression(expression).expression()+'\n\n'
destination = root / 'bemodel-server-py/src/bemodel/value/presentations.py'
destination.parent.mkdir(exist_ok=True)
destination.write_text(output, encoding='utf-8')
