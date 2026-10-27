"""The router: which model answers each call, and what happens when one fails.

- ``state``: quota windows, cooldowns and circuit breakers, shared by every worker
  (``RedisRouterState``) or kept in memory for tests and offline use.
- ``policy``: signals in, an ordered list of candidate models out, with a reason for
  every model left out.
- ``actions``: the failure table, one rule per error kind.
- ``gateway``: one call to one model, with quota reserved first and health recorded after.
- ``router``: sessions that stay on a model, fall back when it fails, hand the conversation
  over mid-task, repair invalid output once, and log every decision with a reason code.
"""
