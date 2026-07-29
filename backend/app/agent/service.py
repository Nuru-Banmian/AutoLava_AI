from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.external_evidence import (
    ExternalEvidenceService,
    NagerPublicHolidayProvider,
    OpenMeteoHistoricalWeatherProvider,
)
from app.agent.factory import create_native_model_adapter
from app.agent.native import (
    NativeExternalEvidenceCollector,
    NativeInvestigationLimits,
    NativeToolAgentService,
    NativeToolModel,
)
from app.agent.tool_access import DatabaseNativeToolScopeResolver
from app.api.routes.agent_admin import agent_enabled
from app.core.config import Settings


def create_agent_service(
    settings: Settings,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    native_model: NativeToolModel | None = None,
    native_now: Callable[[], datetime] | None = None,
    native_evidence_collector: BusinessEvidenceCollector | None = None,
    external_evidence_collector: NativeExternalEvidenceCollector | None = None,
) -> NativeToolAgentService:
    model = native_model or create_native_model_adapter(settings)
    native_options = {"now": native_now} if native_now is not None else {}
    scope_resolver = DatabaseNativeToolScopeResolver(
        session_factory,
        agent_enabled=agent_enabled,
    )
    evidence_collector = (
        native_evidence_collector or BusinessEvidenceCollector(session_factory)
    ).with_scope_authorizer(scope_resolver.refresh_in_session)
    external_collector = external_evidence_collector or ExternalEvidenceService(
        weather_provider=OpenMeteoHistoricalWeatherProvider(),
        holiday_provider=NagerPublicHolidayProvider(),
    )
    return NativeToolAgentService(
        model=model,
        evidence_collector=evidence_collector,
        external_evidence_collector=external_collector,
        scope_resolver=scope_resolver,
        limits=NativeInvestigationLimits(
            max_model_calls=settings.agent_investigation_max_model_calls,
            max_tool_calls=settings.agent_investigation_max_tool_calls,
            timeout_seconds=settings.agent_investigation_timeout_seconds,
            max_tokens=settings.agent_investigation_max_tokens,
            max_cost_eur=settings.agent_investigation_max_cost_eur,
            retry_attempts=settings.agent_investigation_retry_attempts,
        ),
        **native_options,
    )
