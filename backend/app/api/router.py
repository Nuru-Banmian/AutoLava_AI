from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.charts import router as charts_router
from app.api.routes.database import router as database_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.ledger import router as ledger_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(charts_router)
api_router.include_router(admin_router)
api_router.include_router(ledger_router)
api_router.include_router(database_router)
api_router.include_router(dashboard_router)
