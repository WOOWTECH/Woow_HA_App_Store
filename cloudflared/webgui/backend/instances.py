"""Shared singleton service instances used by all routers."""
from .logwatch import LogWatcher
from .supervisor import SupervisorClient

supervisor = SupervisorClient()
logwatcher = LogWatcher(supervisor)
