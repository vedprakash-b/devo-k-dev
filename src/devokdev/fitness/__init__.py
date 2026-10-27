"""The model fitness check: what can each model actually do, measured, not assumed.

- ``discovery``: which models each provider serves today, compared with the registry.
- ``probes``: six short tests (instructions, JSON, tool calls, a code fix, recall at
  growing context lengths, speed).
- ``sandbox``: runs model-written code in a locked-down container, never on your machine.
- ``profile``: runs the probes for one model and caches the result as a ``ModelProfile``.

Profiles feed the pre-flight check at plan approval (M3), which compares what a plan
needs with what the available models proved they can do.
"""
