import asyncio
import logging

from fastapi import HTTPException

from app.agents.assistant.graph import ChatModel, create_graph
from app.agents.context import ChatScope
from app.agents.providers.bailian import BailianChat, ModelFailure
from app.agents.memory.service import MemoryService, explicit_content
from app.agents.memory_curator.graph import create_memory_graph
from app.agents.runtime.repository import ChatRepository
from app.core.config import Settings

logger = logging.getLogger(__name__)


class ChatRunner:
    def __init__(self, model: ChatModel, storage: ChatRepository, settings: Settings, *, memory_model=None):
        self.model = model
        self.storage = storage
        self.settings = settings
        self.graph = create_graph(model, storage, settings)
        self.memory = MemoryService(storage)
        memory_settings = settings.model_copy(update={
            "agent_chat_base_url": settings.agent_memory_base_url,
            "agent_chat_api_key": settings.agent_memory_api_key,
            "agent_chat_model": settings.agent_memory_model,
            "agent_timeout_seconds": settings.agent_memory_timeout_seconds,
            "agent_output_tokens": 1024,
        })
        self.memory_model = memory_model if memory_model is not None else BailianChat(memory_settings)
        self.memory_graph = create_memory_graph(self.memory_model, self.memory, settings)
        self.tasks: set[asyncio.Task] = set()
        self.runs: dict[str, asyncio.Task] = {}

    async def submit(self, scope: ChatScope, content: str, request_id: str, generation: int):
        is_memory = explicit_content(content) is not None
        model_name = self.memory_model.model_name if is_memory else self.model.model_name
        run, created = await self.storage.submit(scope, content, model_name, request_id, generation)
        if not created:
            return run
        task = asyncio.create_task(self._execute(scope, run.id, is_memory))
        self.runs[run.id] = task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        task.add_done_callback(lambda _: self.runs.pop(run.id, None))
        return run

    async def stop(self, scope: ChatScope, run_id: str):
        run = await self.storage.stop(scope, run_id)
        if task := self.runs.get(run_id):
            task.cancel()
        return run

    async def reset(self, scope: ChatScope, generation: int):
        for run_id in await self.storage.reset(scope, generation):
            if task := self.runs.get(run_id):
                task.cancel()
        return await self.storage.conversation(scope)

    async def _execute(self, scope: ChatScope, run_id: str, is_memory=False):
        code = None
        try:
            timeout = self.settings.agent_memory_timeout_seconds if is_memory else self.settings.agent_timeout_seconds
            async with asyncio.timeout(timeout):
                if is_memory:
                    state = await self.memory_graph.ainvoke({"scope": scope, "run_id": run_id})
                    result = state["result"]
                    text = {
                        "saved": "记忆已保存；索引待处理，向量检索尚未就绪。",
                        "already_saved": "这条记忆已保存，已补充本次来源；向量检索尚未就绪。",
                        "pending_confirmation": "内容存在冲突，已记录为待确认，尚未成为有效记忆。候选处理将在后续开放。",
                        "not_saved": "未保存：当前内容不适合作为长期偏好或门店背景，请明确表达需要长期保留的信息。",
                    }[result["status"]]
                    await self.storage.record(scope, run_id, "delta", {"text": text})
                    await self.storage.record(scope, run_id, "completed", {"status": "completed"})
                else:
                    await self.graph.ainvoke({"scope": scope, "run_id": run_id, "messages": []})
        except TimeoutError:
            code = "memory_model_timeout" if is_memory else "model_timeout"
        except ModelFailure as exc:
            code = "memory_" + exc.code if is_memory and exc.code.startswith("model_") else exc.code
        except HTTPException:
            code = "access_revoked"
        except asyncio.CancelledError:
            code = "interrupted"
        except Exception:
            code = "internal_error"
        if code:
            try:
                await self.storage.fail(scope, run_id, code)
            except Exception:
                # Never log exception bodies or state: providers may include private inputs.
                logger.error("agent_run_failure_persistence run_id=%s", run_id)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
