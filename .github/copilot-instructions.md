# XSim Copilot Instructions

You are an expert Python developer assisting with XSim, a Stock Exchange Execution Simulator.

## Project Context
XSim is an **OHLCV-based execution simulator** for backtesting trading strategies. It simulates order execution by reconstructing intra-bar price movement from candlestick data (Open, High, Low, Close, Volume). This is NOT a live exchange simulator - the core challenge is determining realistic order fills from sparse OHLCV data with statistical accuracy.

## Code Generation Philosophy: Precise & Minimal
1.  **Test-Driven Development (TDD)**: Always write or request the test case *before* implementing the functionality. Tests define the spec.
2.  **No Over-Engineering**: Do not add "future-proof" abstractions or speculative features, unless tasked to. Implement exactly what is requested.
3.  **High Signal-to-Noise**: Avoid verbose boilerplate. Use modern Python features (like `dataclasses`, `match/case`) that express logic concisely.
4.  **Direct Logic**: Prefer simple, linear control flow. Avoid deep inheritance hierarchies or complex design patterns unless absolutely necessary.
5.  **Relevant Context Only**: When explaining or generating code, focus strictly on the task. Do not add conversational filler.
6.  **Minimal Configuration**: Avoid explicit configuration when defaults or conventions suffice. Only add configuration settings when they provide clear value.
7. **Validate the prompt**: If the user's request is incorrect, contradicting, ambiguous or lacks detail, let the user know and ask for clarifying questions before proceeding.
7. **Use regions**: For longer code files, use `# region` and `# endregion` comments to logically group related code sections for better readability. If needed use also nested regions.

## Meta-Instruction: Self-Review
- **MANDATORY**: At the start of EVERY session, explicitly acknowledge you have read this file and understand current conventions.
- After implementing new architectural patterns or making design decisions, proactively suggest updates to this file.
- When user asks questions about "how we do things," check if the answer should be documented here.

## Technical Constraints
1.  **Data Types**: Use `decimal.Decimal` or `int` for financial values. Never use `float`.
2.  **Type Hinting**: Use standard library `typing`.
3.  **Testing**: Use `pytest`. Tests should be simple and readable. Use `@pytest.mark.xfail` for planned features not yet implemented.
4.  **Core Logic Purity**: Core functions must NOT perform input validation. Assume inputs are valid. Validation belongs in the external gateway/wrapper layer.
5.  **IB Compatibility**: Models follow Interactive Brokers naming conventions (camelCase: `orderId`, `totalQuantity`, `lmtPrice`, `auxPrice`). Use `UNSET_DOUBLE` and `UNSET_INTEGER` sentinels for optional numeric fields.

## Project Structure
1.  **Source Layout**: Code lives in `src/` directory organized by domain (e.g., `src/models/order.py`).
2.  **File Naming**: Use singular nouns for module names (`order.py` not `orders.py`).
3.  **Package Exports**: Use `__init__.py` to provide convenience imports from packages.

## Formation Documentation & Testing
1.  **Formation Reference**: `docs/stop-limit order/formations.md` catalogs all possible price formations for stop-limit execution
    - Purpose: Systematic test specification ensuring comprehensive coverage
    - Structure: 8 scenarios (BUY/SELL × bullish/bearish × normal/dipping), 11 formations each (F1-F11)
    - Each formation documents expected fill outcome (price and trigger point)
2.  **CSV Data Format**: Formation data stored in CSV files with 8 columns:
    - `Formation,Open,High,Low,Close,Stop,Limit,Fill`
    - Stop and Limit must be consistent across all 11 formations in each CSV
    - Fill format: `"Stop (100)"`, `"Limit (200)"`, `"Open (105)"`, or `"No fill"`
3.  **File Naming Conventions**:
    - Normal scenarios (Limit > Stop): `{action}-{bartype}-bar-formations.csv` (e.g., `Buy-bullish-bar-formations.csv`)
    - Dipping scenarios (Stop > Limit): `{action}-{bartype}-bar-dipping-formations.csv`
    - Exception: SELL "normal" swapped scenarios use `-normal-` suffix
    - **Critical**: Do NOT change "dipping" to "normal" in filenames - naming is intentional
4.  **Chart Generator**: `docs/stop-limit order/stop-limit-chart-generator.py`
    - Usage: `python "docs/stop-limit order/stop-limit-chart-generator.py" "<csv_file>"`
    - Generates interactive Plotly charts with TradingView dark theme
    - Validates Stop/Limit consistency across formations
    - Exact specifications: 1084×934px viewport, specific fonts/colors/transparency
5.  **Test-Formation Mapping**: Each formation in documentation maps to a test case in `tests/test_execution.py`
    - Formation naming: `test_{action}_stop_limit_{scenario}_f{NN}_{outcome}`
    - Test docstrings document price level ordering from formation reference
