import asyncio
import logging

from fastapi import HTTPException

from app.agents.assistant.graph import ChatModel, create_graph
from app.agents.context import ChatScope
from app.agents.providers.bailian import ModelFailure
from app.agents.runtime.repository import ChatRepository
from app.core.config import Settings

logger = logging.getLogger(__name__)


class ChatRunner:
    def __init__(self, model: ChatModel, storage: ChatRepository, settings: Settings):
        self.model = model
        self.storage = storage
        self.settings = settings
        self.graph = create_graph(model, storage, settings)
        self.tasks: set[asyncio.Task] = set()

    async def submit(self, scope: ChatScope, content: str):
        run = await self.storage.submit(scope, content, self.model.model_name)
        task = asyncio.create_task(self._execute(scope, run.id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return run

    async def _execute(self, scope: ChatScope, run_id: str):
        code = None
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                await self.graph.ainvoke({"scope": scope, "run_id": run_id, "messages": []})
        except TimeoutError:
            code = "model_timeout"
        except ModelFailure as exc:
            code = exc.code
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
