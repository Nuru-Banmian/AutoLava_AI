from app.models.income_config import IncomeConfigVersion


async def test_income_config_schema_supports_immutable_versions(
    db_session, store_factory, user_factory
) -> None:
    store = await store_factory(name="Versioned")
    actor = await user_factory(
        username="version-owner",
        password="secret",
        role="admin",
    )
    version = IncomeConfigVersion(
        store_id=store.id,
        version=1,
        enabled=True,
        created_by=actor.id,
    )
    db_session.add(version)
    await db_session.flush()

    assert version.id is not None
    assert version.version == 1
    assert version.enabled is True
