"""bd_agent/tools — Tool registry, curated tools, and SQL fallback tool.

Zero imports from src.* (RF-070). Depends only on:
- bd_agent.contracts (DatabaseGateway, ToolCall, ToolResult)
- bd_agent.safety.sqlglot_validator (for sql_fallback)
"""
