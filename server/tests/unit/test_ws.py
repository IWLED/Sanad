"""اختبارات قناة WebSocket للمصادقة والاستئناف ورسائل التحكم وتبادل القرارات."""

import asyncio
import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.core.crypto import mint_jwt_access_token
from app.core.hitl.engine import compute_args_hash
from app.db.base import async_session_factory
from app.db.models import Action, Device
from app.main import create_app


@pytest.fixture
def test_client() -> TestClient:
    return TestClient(create_app())


def test_ws_unauthorized_token_rejected(test_client: TestClient) -> None:
    """التحقق من رفض أي اتصال بـ WebSocket لا يحمل رمز JWT صالحاً."""
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        test_client.websocket_connect("/v1/ws?token=invalid_token"),
    ):
        pass
    assert exc.value.code == 1008


def test_ws_lifecycle_and_messages(test_client: TestClient) -> None:
    """التحقق من دورة حياة الاتصال: hello, ping/pong, action_decision عبر WebSocket."""
    now_iso = datetime.now(UTC).isoformat()
    suffix = secrets.token_hex(6)
    device_id = f"dev_ws_{suffix}"
    action_id = f"act_ws_{suffix}"

    args_dict = {"recipient": "+966500000000", "message": "اختبار القرار عبر WS"}
    args_hash = compute_args_hash(args_dict)

    async def _setup_data() -> None:
        async with async_session_factory() as session:
            dev = Device(
                id=device_id,
                name="WS Test Device",
                pubkey_pem="fake_pem",
                created_at=now_iso,
            )
            await session.merge(dev)

            act = Action(
                id=action_id,
                version=1,
                kind="mock_t2",
                executor="device",
                risk_tier=2,
                args_json='{"recipient": "+966500000000", "message": "اختبار القرار عبر WS"}',
                args_hash=args_hash,
                preview_json='{"title": "اختبار", "draft_text": "اختبار"}',
                origin_event_ids_json="[]",
                warnings_json="[]",
                status="PENDING_APPROVAL",
                idempotency_key=f"idem_ws_{suffix}",
                created_at=now_iso,
                expires_at=datetime(2099, 1, 1, tzinfo=UTC).isoformat(),
            )
            await session.merge(act)
            await session.commit()

    asyncio.run(_setup_data())

    token, _ = mint_jwt_access_token(device_id)

    with test_client.websocket_connect(f"/v1/ws?token={token}") as ws:
        # 1. إرسال ping وتلقي pong
        ws.send_json({"v": 1, "type": "ping", "payload": {}})
        resp_pong = ws.receive_json()
        assert resp_pong["type"] == "pong"
        assert "server_time" in resp_pong["payload"]

        # 2. إرسال hello وتلقي welcome
        ws.send_json({"v": 1, "type": "hello", "payload": {"last_seq": 0}})
        resp_welcome = ws.receive_json()
        assert resp_welcome["type"] == "welcome"
        assert resp_welcome["payload"]["resume"] == "ok"

        # 3. إرسال قرار اعتماد action_decision
        decision_payload = {
            "action_id": action_id,
            "version": 1,
            "args_hash": args_hash,
            "decision": "APPROVE",
        }
        ws.send_json({"v": 1, "type": "action_decision", "payload": decision_payload})

        # يجب أن يرسل الخادم exec_command للجهاز ثم action_update
        # قد تأتي exec_command أولاً ثم action_update
        msg1 = ws.receive_json()
        msg2 = ws.receive_json()
        received_types = {msg1["type"], msg2["type"]}
        assert "exec_command" in received_types
        assert "action_update" in received_types
