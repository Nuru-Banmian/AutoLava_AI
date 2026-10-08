"""Bailian's OpenAI-compatible text embedding endpoint, configured independently."""
import math

import httpx

from app.agents.providers.bailian import ModelFailure


class BailianEmbedding:
    def __init__(self, settings):
        self.settings = settings

    async def embed(self, text):
        s = self.settings
        if not (s.agent_embedding_base_url and s.agent_embedding_api_key.get_secret_value()
                and s.agent_embedding_model and s.agent_embedding_dimensions):
            raise ModelFailure("embedding_not_configured")
        if not s.agent_embedding_base_url.startswith("https://"):
            raise ModelFailure("embedding_configuration")
        try:
            async with httpx.AsyncClient(timeout=s.agent_embedding_timeout_seconds) as client:
                response = await client.post(s.agent_embedding_base_url.rstrip("/") + "/embeddings",
                    headers={"Authorization": "Bearer " + s.agent_embedding_api_key.get_secret_value()},
                    json={"model": s.agent_embedding_model, "input": [text],
                          "dimensions": s.agent_embedding_dimensions, "encoding_format": "float"})
                response.raise_for_status()
                vector = response.json()["data"][0]["embedding"]
            if (not isinstance(vector, list) or len(vector) != s.agent_embedding_dimensions
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
                    or not any(vector)):
                raise ValueError("Invalid vector")
            return vector
        except httpx.TimeoutException as exc:
            raise ModelFailure("embedding_timeout") from exc
        except httpx.HTTPError as exc:
            raise ModelFailure("embedding_unavailable") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelFailure("embedding_format") from exc
