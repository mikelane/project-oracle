"""MCP contract tests — verify the server exposes the correct tools with correct schemas."""

from __future__ import annotations

import pytest


@pytest.mark.small
class DescribeMCPContract:
    async def it_exposes_exactly_six_tools(self) -> None:
        from oracle.server import mcp

        tools = await mcp.list_tools()
        assert len(tools) == 6

    async def it_exposes_all_required_tool_names(self) -> None:
        from oracle.server import mcp

        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        required = {
            "oracle_read",
            "oracle_grep",
            "oracle_status",
            "oracle_run",
            "oracle_ask",
            "oracle_forget",
        }
        assert required <= tool_names

    async def it_oracle_read_requires_path_parameter(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_read"].inputSchema
        assert "path" in schema["properties"]
        assert schema["properties"]["path"]["type"] == "string"

    async def it_oracle_run_requires_commands_list(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_run"].inputSchema
        assert "commands" in schema["properties"]

    async def it_oracle_grep_has_pattern_parameter(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_grep"].inputSchema
        assert "pattern" in schema["properties"]

    async def it_oracle_ask_requires_question_string(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_ask"].inputSchema
        assert "question" in schema["properties"]

    async def it_oracle_forget_requires_path_parameter(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_forget"].inputSchema
        assert "path" in schema["properties"]
        assert schema["properties"]["path"]["type"] == "string"

    async def it_oracle_status_has_no_required_parameters(self) -> None:
        from oracle.server import mcp

        tools = {t.name: t for t in await mcp.list_tools()}
        schema = tools["oracle_status"].inputSchema
        required = schema.get("required", [])
        assert len(required) == 0
