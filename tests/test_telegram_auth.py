"""Auth helper unit tests (no network)."""

from __future__ import annotations

import pytest

from app.telegram.auth import TelegramAuthError, TelegramAuthenticator, _mask_phone


def test_mask_phone() -> None:
    assert _mask_phone("+60123456789") == "+60****89"
    assert _mask_phone("123") == "****"
    assert _mask_phone(None) is None


@pytest.mark.asyncio
async def test_auth_requires_phone_provider() -> None:
    client = object()  # unused — we fail before connect if not authorized path
    # Build authenticator without providers; mock client methods
    from unittest.mock import AsyncMock, MagicMock

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    mock_client.is_user_authorized = AsyncMock(return_value=False)

    auth = TelegramAuthenticator(mock_client)
    with pytest.raises(TelegramAuthError, match="Phone provider"):
        await auth.ensure_authorized()
