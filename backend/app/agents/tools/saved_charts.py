"""Authorized UI access to saved drawings; never Agent answer evidence."""
from sqlalchemy import select

from app.models.agent import AgentChart, AgentConversation, AgentMessage


async def authorized_chart(session, scope, message_id, chart_id):
    return await session.scalar(select(AgentChart).join(AgentMessage).join(AgentConversation).where(
        AgentChart.chart_id == chart_id, AgentChart.message_id == message_id,
        AgentMessage.role == "assistant", AgentConversation.user_id == scope.user_id,
        AgentConversation.store_id == scope.store_id,
    ))
