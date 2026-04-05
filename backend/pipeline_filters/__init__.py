"""
Pipeline filters for Open WebUI.

Filters intercept messages before they reach the LLM (inlet) and after the
LLM responds (outlet).  They are used for content moderation, prompt
rewriting, RAG injection, and response post-processing.
"""
