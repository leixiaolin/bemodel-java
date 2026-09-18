"""Preserve Java prompt wording as Python constants at migration time."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
java = root / 'bemodel-server/src/main/java/com/bemodel/cs'
cs = (java / 'CsService.java').read_text(encoding='utf-8')
semantic = (java / 'SemanticQaService.java').read_text(encoding='utf-8')


def literals(source):
    return ''.join(json.loads(m.group()) for m in re.finditer(r'"(?:\\.|[^"\\])*"', source))


route = cs.split('String routePrompt(String q)')[1].split('List<CsFeedback> mistakes')[0]
analytics = cs.split('String analyticsRoutePrompt(String q)')[1].split('/** 路由反馈')[0]
plan = semantic.split('private String buildPlanPrompt(String q)')[1].split('// ---------- 3.')[0]
plan = plan.replace('LocalDate.now()', '"__TODAY__"').replace('+ q +', '+ "__QUESTION__" +')
values = dict(CS_ROUTE_PROMPT=literals(route), ANALYTICS_ROUTE_PROMPT=literals(analytics), SEMANTIC_PLAN_PROMPT=literals(plan))
destination = root / 'bemodel-server-py/src/bemodel/cs/prompts.py'
destination.write_text('# Original Java prompt text, extracted by scripts/extract_cs_prompts.py.\n'+''.join(f'{key} = {value!r}\n\n' for key, value in values.items()), encoding='utf-8')
