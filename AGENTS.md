# AGENTS.md

This file guides coding agents working in this repository. Keep changes scoped, preserve the existing architecture, and update this document when project conventions change.

## Project Overview

BeModel is a semantic-layer platform for hospital business systems. It keeps operational data in source databases and maintains ontology, mapping, rules, metrics, lineage, governance, clinical QA, RCA, AI customer-service, and analytics capabilities on top.

The repository contains three main parts:

- `bemodel-server/`: Java 21 Spring Boot backend. This is the original service and production-shaped reference implementation.
- `bemodel-server-py/`: Python 3.12 FastAPI + SQLAlchemy backend. It is a Java-compatible migration that preserves API paths, auth rules, MySQL schema behavior, seed data, and response semantics where possible.
- `bemodel-web/`: Vue 3 + Vite frontend using Element Plus, ECharts, Pinia, and axios.

## Repository Map

- `README.md`: product overview, screenshots, quick start, environment variables, demo accounts.
- `docs/`: migration plans, operational notes, and screenshots.
- `bemodel-server/src/main/java/com/bemodel/`: Java domain modules.
- `bemodel-server/src/main/resources/db/migration/`: Flyway migrations `V1` through `V28`.
- `bemodel-server/src/main/resources/shacl/`: SHACL constraints used by RDF/ontology validation.
- `bemodel-server/src/test/java/com/bemodel/`: Java tests by domain.
- `bemodel-server-py/src/bemodel/`: FastAPI backend modules mirroring the Java domains.
- `bemodel-server-py/src/bemodel/db/migration/`: Python-packaged copy of SQL migrations.
- `bemodel-server-py/tests/`: Python unit and integration tests.
- `bemodel-server-py/scripts/`: parity, replay, migration, and verification utilities.
- `bemodel-web/src/api/`: axios API wrappers. Requests use `baseURL: /api` and attach JWT automatically.
- `bemodel-web/src/views/`: page-level Vue views.
- `bemodel-web/src/styles/`: design tokens and theme overrides.
- `output/`: UI test scripts and captured screenshots.

## Domain Modules

Common module names are shared across Java, Python, and frontend where practical:

- `auth`: login, JWT, roles `ADMIN`, `EDITOR`, `VIEWER`.
- `ontology`: domains, concepts, attributes, relations, metrics, terms, OWL import, drift/miss services.
- `modeling`: rules, actions, axioms, releases, release gates.
- `datasource`: external database registration, encrypted secrets, schema scanning.
- `instance`: semantic mappings between ontology attributes and physical table columns.
- `rdf`: Turtle/OWL export and SHACL validation.
- `cs`: AI customer service and analytics question answering.
- `llm`: DeepSeek gateway and audit logging.
- `search`: semantic search.
- `governance`: data quality scans, rules, and issues.
- `clinical`: clinical QA and alerts.
- `flow`: order/settlement closed-loop demo flows.
- `link`: bidirectional lineage tracing.
- `impact`: multi-hop change impact analysis.
- `rca`: root cause analysis.
- `notice`: inspection and in-app alerts.
- `value`: value proof pages and APIs.
- `agents`: Python-only. Microsoft Agent Framework adapter plus the semantic-QA SQL critic agent.

## Common Commands

Run commands from the indicated directory.

### Java Backend

```powershell
cd bemodel-server
mvn test
mvn spring-boot:run
```

The Java service listens on `http://127.0.0.1:18080`.

### Python Backend

```powershell
cd bemodel-server-py
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m uvicorn bemodel.main:app --host 127.0.0.1 --port 18080
```

Start Python from `bemodel-server-py/` when using `.env`. It uses the same default port as Java, so only run one backend on `18080` at a time.

### Python MySQL Integration Tests

Run from the repository root:

```powershell
$env:BEMODEL_TEST_MYSQL_PORT='13317'
docker compose -p bemodel-python-candidate -f bemodel-server-py/compose.test.yml up -d --wait
$env:MYSQL_HOST='127.0.0.1'
$env:MYSQL_PORT='13317'
$env:MYSQL_USERNAME='root'
$env:MYSQL_PASSWORD='bemodel-isolated-test-only'
$env:MYSQL_DATABASE='bemodel_py_test'
$env:DEEPSEEK_API_KEY=''
$env:BEMODEL_DISABLE_SCHEDULER='1'
.\bemodel-server-py\.venv\Scripts\python.exe bemodel-server-py/scripts/bootstrap_test_db.py
$env:BEMODEL_MYSQL_TESTS='1'
.\bemodel-server-py\.venv\Scripts\python.exe -m pytest bemodel-server-py/tests -q
```

The integration setup is intentionally isolated. Do not point tests at a developer or production database.

### Frontend

```powershell
cd bemodel-web
pnpm install
pnpm dev
pnpm build
```

Vite runs on `http://127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:18080`.

## Environment Variables

Shared service configuration:

- `MYSQL_HOST`: default `127.0.0.1`.
- `MYSQL_PORT`: default `3306`.
- `MYSQL_DATABASE`: default `bemodel_platform`.
- `MYSQL_USERNAME`: database user. Required outside trivial local defaults.
- `MYSQL_PASSWORD`: database password. Required outside trivial local defaults.
- `JWT_SECRET`: JWT signing secret. Required for production.
- `APP_SECRET_KEY`: AES-GCM secret for datasource password encryption. Required for production.
- `DEEPSEEK_API_KEY`: optional. Empty value enables rule/template fallback.

Python-only settings:

- `BEMODEL_DISABLE_SCHEDULER=1`: disable metric inspection scheduler.
- `BEMODEL_INSPECT_CRON`: six-field cron expression including seconds.

Never commit secrets or `.env` files.

## Data And Migration Rules

- Java Flyway migrations in `bemodel-server/src/main/resources/db/migration/` are the source schema history.
- Python packages matching migrations under `bemodel-server-py/src/bemodel/db/migration/` for Java parity. Keep migration content aligned when changing schema.
- Startup runs migrations, migrates datasource secrets, seeds demo data, and starts inspection scheduling.
- Demo data includes platform metadata plus nine demo business databases. Treat seed data as deterministic fixtures unless a task explicitly changes demo scenarios.
- Preserve existing table names, JSON shapes, pagination defaults, and error text when maintaining Java/Python parity.

## API And Response Conventions

- HTTP APIs live under `/api`.
- Java controllers and FastAPI routers should keep matching methods, paths, auth behavior, and response envelopes where a route exists in both.
- Frontend `src/api/request.js` unwraps backend responses of shape `{ code, msg, data }`; `code === 0` returns `data`, otherwise it displays `msg`.
- Unauthorized responses clear frontend user state and redirect to `/login`.
- `403` means the user lacks `EDITOR` or `ADMIN` permissions for write/admin operations.

## Security Rules

- Keep anonymous write operations closed.
- Maintain role semantics: `ADMIN` has full capability, `EDITOR` can write/model but not manage users, `VIEWER` is read-only plus question answering/search.
- Datasource passwords must remain encrypted at rest with the existing AES-GCM mechanism and `ENC:` ciphertext prefix.
- RDF/export paths must preserve existing sensitive-field masking behavior.
- SQL generated or accepted for analytics must continue to pass whitelist/safety validation.
- Do not log API keys, datasource passwords, JWT secrets, or raw patient-sensitive exports.

## Java Backend Guidance

- Follow the existing Spring Boot package layout: controller, service, mapper, entity as already used by each module.
- MyBatis-Plus maps underscore columns to camelCase Java fields.
- Keep common return and exception semantics in `com.bemodel.common`.
- Add Flyway migrations for schema changes; do not edit already-applied migrations unless the task is explicitly local/prototype work.
- For ontology/RDF/SHACL behavior, respect Apache Jena 5.2.0 usage already in the codebase.
- Prefer tests under `bemodel-server/src/test/java/com/bemodel/<module>/` for behavior changes.

## Python Backend Guidance

- Preserve compatibility with Java unless the task explicitly asks to diverge.
- Routers are registered in `src/bemodel/main.py`; new public routes need inclusion there.
- Use SQLAlchemy sessions consistently with existing service patterns.
- Keep `.env` loading and settings in `src/bemodel/config.py`.
- Package any runtime SQL, SHACL, or seed resources through `pyproject.toml` package data.
- Use `create_app(startup=False)` in tests when startup side effects are not needed.
- Remember that Python reports SHACL engine metadata as `pySHACL`; Java reports `Apache Jena SHACL 5.2.0`. Compare violation content separately.

## Frontend Guidance

- Use Vue 3 composition consistent with existing views.
- Use Element Plus components and `@element-plus/icons-vue` icons where suitable.
- Add API functions under `src/api/` rather than calling axios directly from views.
- Keep route registration in `src/router/index.js`; authenticated routes live under `MainLayout`.
- Preserve the design-token approach in `src/styles/tokens.css` and existing dark navigation layout.
- Avoid hardcoding backend hostnames in application code; rely on Vite `/api` proxy and axios `baseURL`.
- Handle `VIEWER` read-only behavior in the UI when adding write controls.

## Testing Strategy

- For Java-only backend logic, run `mvn test` in `bemodel-server/`.
- For Python logic without database dependency, run `.\.venv\Scripts\python.exe -m pytest tests -q` in `bemodel-server-py/`.
- For Python schema/seed/API parity, use the isolated Docker MySQL flow.
- For frontend changes, run `pnpm build` in `bemodel-web/`; run UI manually against a live backend for interaction-heavy changes.
- For API parity work, inspect or run scripts in `bemodel-server-py/scripts/`, especially route coverage, replay diff, seed parity, flow parity, RCA/CS parity, and crypto interop.

## Change Hygiene

- Keep edits narrow and module-local.
- Do not reformat unrelated files.
- Do not commit generated caches, virtual environments, local env files, or screenshots unless explicitly part of the task.
- Be careful with encoding: source and docs are intended to be UTF-8 and contain Chinese text.
- Before touching security, migration, or parity code, read both the Java and Python implementations for the same module.
- If a change affects API contracts, update both backend implementations or clearly document why only one side changed.

中文回复

冻结java版本的后端bemodel-server，所有新增、优化、扩展的后端功能都由python版本的bemodel-server-py实现。
