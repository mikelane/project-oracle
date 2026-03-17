"""Tests for ChunkhoundClient — MCP-over-MCP semantic search client."""

from __future__ import annotations

import asyncio

import pytest
from pytest_mock import MockerFixture

from oracle.integrations.chunkhound import ChunkhoundClient


class DescribeChunkhoundClient:
    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_fails_gracefully_when_not_installed(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=mocker.AsyncMock,
            side_effect=FileNotFoundError("chunkhound not found"),
        )
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
    async def it_starts_successfully_when_binary_exists(
        self, mocker: MockerFixture
    ) -> None:
        mock_process = mocker.AsyncMock()
        mocker.patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=mocker.AsyncMock,
            return_value=mock_process,
        )
        client = ChunkhoundClient("/fake/path")
        result = await client.try_start()
        assert result is True
        assert client._started is True
        assert client.process is mock_process

    @pytest.mark.asyncio
    async def it_returns_true_if_already_started(self, mocker: MockerFixture) -> None:
        client = ChunkhoundClient("/fake/path")
        client._started = True
        client.process = mocker.MagicMock()
        result = await client.try_start()
        assert result is True

    @pytest.mark.asyncio
    async def it_returns_empty_list_when_started_but_v1(
        self, mocker: MockerFixture
    ) -> None:
        """V1 chunkhound search always returns empty (best-effort stub)."""
        client = ChunkhoundClient("/fake/path")
        client._started = True
        client.process = mocker.MagicMock()
        results = await client.search("some query", max_results=3)
        assert results == []

    @pytest.mark.asyncio
    async def it_stops_running_process(self, mocker: MockerFixture) -> None:
        client = ChunkhoundClient("/fake/path")
        mock_process = mocker.AsyncMock()
        mock_process.terminate = mocker.MagicMock()
        mock_process.kill = mocker.MagicMock()
        mock_process.wait = mocker.AsyncMock(return_value=0)
        client.process = mock_process
        client._started = True

        await client.stop()

        mock_process.terminate.assert_called_once()
        assert client._started is False

    @pytest.mark.asyncio
    async def it_kills_process_on_stop_timeout(self, mocker: MockerFixture) -> None:
        client = ChunkhoundClient("/fake/path")
        mock_process = mocker.AsyncMock()
        mock_process.terminate = mocker.MagicMock()
        mock_process.kill = mocker.MagicMock()
        mock_process.wait = mocker.AsyncMock(side_effect=asyncio.TimeoutError)
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
    async def it_handles_timeout_during_start(self, mocker: MockerFixture) -> None:
        """If subprocess takes too long, try_start returns False."""
        mocker.patch(
            "oracle.integrations.chunkhound.asyncio.create_subprocess_exec",
            new_callable=mocker.AsyncMock,
            side_effect=asyncio.TimeoutError,
        )
        # We need to also patch wait_for to propagate the timeout
        client = ChunkhoundClient("/fake/path")
        result = await client.try_start()
        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.medium
    async def it_handles_os_error_during_start(self, mocker: MockerFixture) -> None:
        """If spawning fails with OSError, try_start returns False."""
        mocker.patch(
            "oracle.integrations.chunkhound.asyncio.wait_for",
            new_callable=mocker.AsyncMock,
            side_effect=OSError("spawn failed"),
        )
        client = ChunkhoundClient("/fake/path")
        result = await client.try_start()
        assert result is False
