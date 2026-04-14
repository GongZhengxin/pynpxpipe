"""Agent layer — LLM-powered assistant modules.

Peers: core, io, stages, ui. This package holds features that depend on an
LLM backend (chat help, future RAG or tool-use agents). Keeping them
isolated from `core/` ensures the `openai` SDK dependency is opt-in.
"""
