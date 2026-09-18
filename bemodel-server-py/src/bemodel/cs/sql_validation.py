"""Java-compatible semantic SQL whitelist and row-limit validation."""
import re
from bemodel.core.exceptions import BizException

FORBIDDEN = set('INSERT UPDATE DELETE DROP ALTER TRUNCATE CREATE GRANT REVOKE REPLACE LOAD CALL EXEC EXECUTE HANDLER LOCK UNLOCK SET INTO OUTFILE'.split())
KEYWORDS = set('SELECT FROM WHERE JOIN LEFT RIGHT INNER OUTER CROSS ON GROUP BY ORDER HAVING LIMIT AS AND OR NOT IN IS NULL LIKE BETWEEN EXISTS CASE WHEN THEN ELSE END DISTINCT UNION ALL ASC DESC TRUE FALSE INTERVAL COUNT SUM AVG MAX MIN NOW CURDATE CURRENT_DATE CURRENT_TIMESTAMP DATE DATEDIFF DATE_FORMAT IFNULL IF COALESCE ROUND CAST CONCAT SUBSTRING YEAR MONTH DAY CHAR SIGNED UNSIGNED DECIMAL'.split())
IDENT = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')
FROM_JOIN = re.compile(r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?', re.I)
LIMIT = re.compile(r'\blimit\s+(\d+)', re.I)


def strip_comments_and_literals(sql):
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if sql.startswith('--', i) or c == '#':
            while i < n and sql[i] != '\n':
                i += 1
        elif sql.startswith('/*', i):
            end = sql.find('*/', i+2)
            i = n if end < 0 else end+2
        elif c in ('\'', '"'):
            i += 1
            while i < n:
                if sql[i] == '\\':
                    i += 2
                    continue
                if sql[i] == c:
                    if i+1 < n and sql[i+1] == c:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append(' ')
        elif c == '`':
            i += 1
            while i < n and sql[i] != '`':
                out.append(sql[i])
                i += 1
            i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def next_is(s, position, c):
    return s[position:].lstrip().startswith(c)


def prev_is(s, position, c):
    return s[:position].rstrip().endswith(c)


def validate_sql(sql, allowed_tables, allowed_columns):
    if not sql or not sql.strip():
        raise BizException('SQL 为空')
    cleaned = strip_comments_and_literals(sql)
    if ';' in cleaned:
        raise BizException('不允许多语句（含分号）')
    if not cleaned.split() or cleaned.split()[0].upper() != 'SELECT':
        raise BizException('只允许 SELECT 查询')
    for bad in sorted(FORBIDDEN):
        if re.search(r'(?<![a-zA-Z0-9_])'+bad+r'(?![a-zA-Z0-9_])', cleaned, re.I):
            raise BizException('SQL 含禁用关键字: '+bad)
    tables, columns, aliases = {t.lower() for t in allowed_tables}, {c.lower() for c in allowed_columns}, set()
    for match in FROM_JOIN.finditer(cleaned):
        table, alias = match.groups()
        if table.lower() not in tables:
            raise BizException('表不在该数据源的映射白名单: '+table.lower())
        if alias and alias.upper() not in KEYWORDS:
            aliases.add(alias.lower())
    aliases.update(m.group(1).lower() for m in re.finditer(r'\bas\s+([a-zA-Z_][a-zA-Z0-9_]*)', cleaned, re.I))
    first_from = re.search(r'(?<![a-zA-Z0-9_])from(?![a-zA-Z0-9_])', cleaned, re.I)
    clause = cleaned[:first_from.start()] if first_from and first_from.start() > 0 else cleaned
    expect_expr = False
    for match in IDENT.finditer(clause):
        identifier = match.group()
        if identifier.upper() in KEYWORDS:
            expect_expr = identifier.upper() in {'SELECT', 'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE'}
            continue
        if next_is(clause, match.end(), '('):
            expect_expr = False
            continue
        if prev_is(clause, match.start(), ',') or prev_is(clause, match.start(), '(') or prev_is(clause, match.start(), '.') or next_is(clause, match.end(), '.'):
            expect_expr = True
        if not expect_expr:
            aliases.add(identifier.lower())
        expect_expr = False
    for match in IDENT.finditer(cleaned):
        identifier, low = match.group(), match.group().lower()
        if identifier.upper() in KEYWORDS or low in aliases or low in tables or next_is(cleaned, match.end(), '('):
            continue
        if prev_is(cleaned, match.start(), '.'):
            if low not in columns:
                raise BizException('列不在映射白名单: '+identifier)
            continue
        if next_is(cleaned, match.end(), '.'):
            if low not in tables and low not in aliases:
                raise BizException('限定词不在白名单: '+identifier)
            continue
        if low not in columns:
            raise BizException('列不在映射白名单: '+identifier)
    result = sql.strip()
    limit = LIMIT.search(result)
    if limit:
        if int(limit.group(1)) > 100:
            result = result[:limit.start()]+'LIMIT 100'+result[limit.end():]
    else:
        result += ' LIMIT 100'
    return result
