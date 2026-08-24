"""TEMPLATE agent — a Claude Agent SDK agent, self-contained under this directory.

Rename nothing inside this package: every agent keeps the package name ``agent`` so the
Dockerfile, the tests, and the entrypoint are identical across the factory. What differs
between agents is ``agent_config.yaml``, the tools in :mod:`agent.tools`, and the trigger
in :mod:`agent.main`.
"""
