from pathlib import Path
import os
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("VEKTORDB_URL", "http://vectordb:5001")


@pytest.fixture
def tenant_session():
    def _apply(client, tenant_id=1, user_role="admin"):
        with client.session_transaction() as session_data:
            session_data["tenant_id"] = tenant_id
            session_data["user_role"] = user_role
        return client

    return _apply
