"""Persistent local (single process) or remote Qdrant; never an authority for content."""
import hashlib
import json

class MemoryVectors:
    def __init__(self, settings):
        self.settings = settings
        identity = [settings.agent_embedding_base_url, settings.agent_embedding_model,
                    settings.agent_embedding_dimensions, settings.agent_vector_index_version,
                    settings.agent_vector_url or str(settings.agent_vector_path.resolve())
                    if settings.agent_vector_path or settings.agent_vector_url else "disabled"]
        self.fingerprint = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        self.collection = "autolava_memory_" + self.fingerprint
        self.client = None

    async def open(self, *, before_create=None):
        from qdrant_client import AsyncQdrantClient, models

        if self.client is None:
            s = self.settings
            self.client = (AsyncQdrantClient(url=s.agent_vector_url,
                api_key=s.agent_vector_api_key.get_secret_value() or None, timeout=10)
                if s.agent_vector_url else AsyncQdrantClient(path=str(s.agent_vector_path)))
        created = not await self.client.collection_exists(self.collection)
        if created:
            # Invalidate authority BEFORE physical creation: a crash between the two
            # operations must leave pending jobs, never an empty "ready" index.
            if before_create is not None:
                await before_create()
            await self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=self.settings.agent_embedding_dimensions, distance=models.Distance.COSINE))
        info = await self.client.get_collection(self.collection)
        if info.config.params.vectors.size != self.settings.agent_embedding_dimensions:
            raise ValueError("Vector collection dimensions mismatch")
        return created

    async def put(self, memory, vector):
        from qdrant_client import models

        await self.client.upsert(self.collection, points=[models.PointStruct(
            id=memory["id"], vector=vector,
            payload={k: memory[k] for k in ("id", "version", "user_id", "store_id")},
        )], wait=True)

    async def delete(self, memory_id):
        await self.client.delete(self.collection, points_selector=[memory_id], wait=True)

    async def search(self, scope, vector):
        from qdrant_client import models

        result = await self.client.query_points(self.collection, query=vector, limit=12,
            query_filter=models.Filter(must=[
                models.FieldCondition(key="user_id", match=models.MatchValue(value=scope.user_id)),
                models.FieldCondition(key="store_id", match=models.MatchValue(value=scope.store_id)),
            ]), with_payload=True)
        return [point.payload for point in result.points]

    async def verify(self, memory):
        points = await self.client.retrieve(self.collection, ids=[memory["id"]], with_payload=True)
        return bool(points and points[0].payload == {
            k: memory[k] for k in ("id", "version", "user_id", "store_id")})

    async def close(self):
        if self.client is not None:
            await self.client.close()
            self.client = None
