# AGENTS.md
- Always keep the app runnable: `streamlit run app.py`.
- Prefer simple, deterministic fallbacks when OPENAI_API_KEY is missing.
- Log all major steps to logs/events.jsonl and logs/claims.sqlite.
- Keep providers list small (3–6) and hardcoded in data/providers.json for demo.