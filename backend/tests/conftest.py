import pytest

# Make pytest-asyncio default to "auto" so @pytest.mark.asyncio works without
# extra config. Keeps things simple for ad-hoc test files.
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "asyncio" in item.keywords:
            item.add_marker(pytest.mark.asyncio)
