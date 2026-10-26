"""
bot.states
==========
Conversation state identifiers for the Telegram Account Manager bot.
"""

from __future__ import annotations

# ConversationHandler states
PHONE: int = 0
CODE: int = 1
WAITING_FOR_CODE: int = 2
ACCOUNT_ACTIONS: int = 3
