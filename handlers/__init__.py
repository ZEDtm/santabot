# This file makes the handlers directory a Python package
# It can be left empty or used for package-level imports

# Import all handlers to register them
from . import common, admin, user, messaging, gifts, feedback, group_chat
__all__ = ['common', 'admin', 'user', 'messaging', 'gifts', 'feedback', 'group_chat']

def register_handlers(dp):
    """Register all handlers with the dispatcher"""
    common.register_handlers(dp)
    admin.register_handlers(dp)
    user.register_handlers(dp)
    messaging.register_handlers(dp)
    gifts.register_handlers(dp)
    feedback.register_handlers(dp)
