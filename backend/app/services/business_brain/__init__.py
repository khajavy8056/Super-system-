"""v4.0 — Business Brain: the local-first supermarket intelligence layer.

Layout (each module answers exactly one question):

======================================  ==================================================
module                                  question it answers
======================================  ==================================================
``situation``                           what is happening in the shop right now?
``registry`` / ``tools``                what may the brain *do*, and with whose permission?
``agents``                              what does each specialty say about the situation?
``decision_helpers``                    what could be done, and what does each option cost?
``planner`` / ``planner_text``          what should be said to the manager, and why?
``decisions`` / ``followups``           what was decided, what happened, what next?
``memory`` / ``store_profile``          what does the brain know about THIS shop?
``policies``                            what is the owner never willing to allow?
``proactive``                           what should be raised before the manager asks?
``runtime`` / ``model_manager``         which engine is answering, and is it trustworthy?
``grounding`` / ``audit``               can every number be traced, and is it recorded?
``vision``                              the perception interface (no engine shipped)
======================================  ==================================================

The public entry point is :class:`~.brain.BusinessBrain` (or :func:`~.brain.get_brain`).
"""
from __future__ import annotations

__version__ = "4.0.0"

from .brain import ADMIN_SURFACE, BrainDenied, BusinessBrain, get_brain   # noqa: E402

__all__ = ["BusinessBrain", "get_brain", "BrainDenied", "ADMIN_SURFACE", "__version__"]
