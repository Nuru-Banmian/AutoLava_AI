"""Provider-neutral native tool-loop seams for AutoLava Agent investigations."""

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.contracts import EvidenceBundle, EvidenceRequest, ModelMessage, TurnResult
from app.agent.factory import create_native_model_adapter
from app.agent.model import OpenAICompatibleProfile
from app.agent.native import (
    FakeNativeToolModel,
    NativeToolAgentService,
    NativeToolModel,
)
from app.agent.native_model import OpenAICompatibleNativeToolModel

__all__ = [
    "BusinessEvidenceCollector",
    "EvidenceBundle",
    "EvidenceRequest",
    "FakeNativeToolModel",
    "ModelMessage",
    "NativeToolAgentService",
    "NativeToolModel",
    "OpenAICompatibleNativeToolModel",
    "OpenAICompatibleProfile",
    "TurnResult",
    "create_native_model_adapter",
]
