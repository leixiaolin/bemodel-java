from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from bemodel.core.database import engine
from bemodel.core.dynamic_ds import dispose_all
from bemodel.core.handlers import install_handlers
from bemodel.core.migration import run_migrations
from bemodel.core.scheduler import start_scheduler
from bemodel.core.security import SecurityMiddleware
from bemodel.datasource.services import DatasourceService
from bemodel.auth.router import router as auth_router
from bemodel.ontology.router import router as ontology_router
from bemodel.modeling.router import router as modeling_router
from bemodel.datasource.router import router as datasource_router
from bemodel.instance.router import router as instance_router
from bemodel.notice.router import router as notice_router
from bemodel.rdf.router import router as rdf_router
from bemodel.llm.router import router as llm_router
from bemodel.search.router import router as search_router
from bemodel.governance.router import router as governance_router
from bemodel.link.router import router as link_router
from bemodel.architecture.router import router as architecture_router
from bemodel.impact.router import router as impact_router
from bemodel.clinical.router import router as clinical_router
from bemodel.flow.router import router as flow_router
from bemodel.rca.router import router as rca_router
from bemodel.cs.router import router as cs_router
from bemodel.value.router import router as value_router


@asynccontextmanager
async def lifespan(app):
    from starlette.concurrency import run_in_threadpool
    def startup():
        run_migrations(engine)
        with Session(engine, expire_on_commit=False) as session:
            DatasourceService(session).migrate_secrets()
            from bemodel.seed.services import DataSeeder
            DataSeeder(session).run()
        return start_scheduler()
    scheduler = await run_in_threadpool(startup)
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=True)
        dispose_all()
        engine.dispose()


def create_app(*, startup=True):
    app = FastAPI(title="BeModel", lifespan=lifespan if startup else None)
    install_handlers(app)
    for router in (auth_router, ontology_router, modeling_router, datasource_router, instance_router, notice_router, rdf_router, llm_router, search_router, governance_router, link_router, architecture_router, impact_router, clinical_router, flow_router, rca_router, cs_router, value_router):
        app.include_router(router)
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    return app


app = create_app()
