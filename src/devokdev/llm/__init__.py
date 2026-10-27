"""Talking to language models: one conversation format, one adapter, one registry.

- ``messages``: Devo-K-Dev's own (canonical) conversation format.
- ``registry``: providers and models from ``config/models.yaml``.
- ``adapter``: the OpenAI-compatible streaming client every provider is reached through.
- ``errors``: every failure turned into one ``ProviderError`` with a ``kind`` the router acts on.
- ``ratelimits``: reading providers' rate-limit headers.
- ``tokens``: cheap token estimates for budgeting before a call.
"""
