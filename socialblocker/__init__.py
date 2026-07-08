"""SocialBlocker — a Linux desktop focus blocker.

Design (from the project discussion):
  * BLACKLIST is the all-day default: block a handful of core distractions,
    leave the rest of the internet open.
  * WHITELIST is the strict focus mode: only allow specific work sites, block
    the rest. Used for 2-3h deep-work blocks.
  * LOCKED sessions cannot be stopped before their timer ends — the real
    game-changer for people who impulsively disable their blocker.
"""

__version__ = "1.0.0"
