"""Tests for ChunkhoundClient — MCP-over-MCP semantic search client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oracle.integrations.chunkhound import ChunkhoundClient


class DescribeChunkhoundClient:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_fails_gracefully_when_not_installed(self) -> None:
        with patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("chunkhound not found"),
        ):
            client = ChunkhoundClient("/fake/path")
            result = await client.try_start()
            assert result is False
            assert client._started is False

    @pytest.mark.asyncio
    async def it_returns_empty_list_when_not_started(self) -> None:
        client = ChunkhoundClient("/fake/path")
        results = await client.search("find auth handler")
        assert results == []

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_starts_successfully_when_binary_exists(self) -> None:
        mock_process = AsyncMock()
        with patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=AsyncMock,
            return_value=mock_process,
        ):
            client = ChunkhoundClient("/fake/path")
            result = await client.try_start()
            assert result is True
            assert client._started is True
            assert client.process is mock_process

    @pytest.mark.asyncio
    async def it_returns_true_if_already_started(self) -> None:
        client = ChunkhoundClient("/fake/path")
        client._started = True
        client.process = MagicMock()
        result = await client.try_start()
        assert result is True

    @pytest.mark.asyncio
    async def it_returns_empty_list_when_started_but_v1(self) -> None:
        """V1 chunkhound search always returns empty (best-effort stub)."""
        client = ChunkhoundClient("/fake/path")
        client._started = True
        client.process = MagicMock()
        results = await client.search("some query", max_results=3)
        assert results == []

    @pytest.mark.asyncio
    async def it_stops_running_process(self) -> None:
        client = ChunkhoundClient("/fake/path")
        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(return_value=0)
        client.process = mock_process
        client._started = True

        await client.stop()

        mock_process.terminate.assert_called_once()
        assert client._started is False

    @pytest.mark.asyncio
    async def it_kills_process_on_stop_timeout(self) -> None:
        client = ChunkhoundClient("/fake/path")
        mock_process = AsyncMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        client.process = mock_process
        client._started = True

        await client.stop()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert client._started is False

    @pytest.mark.asyncio
    async def it_handles_stop_when_no_process(self) -> None:
        client = ChunkhoundClient("/fake/path")
        # Should not raise
        await client.stop()

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_timeout_during_start(self) -> None:
        """If subprocess takes too long, try_start returns False."""
        with patch(
            "oracle.integrations.chunkhound.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ):
            # We need to also patch wait_for to propagate the timeout
            client = ChunkhoundClient("/fake/path")
            result = await client.try_start()
            assert result is False

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_os_error_during_start(self) -> None:
        """If spawning fails with OSError, try_start returns False."""
        with patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=AsyncMock,
            side_effect=OSError("spawn failed"),
        ):
            client = ChunkhoundClient("/fake/path")
            result = await client.try_start()
            assert result is False
