"""Backward-compatible import path for the hardened player implementation."""

from .player import PLAYER_CSS, PLAYER_JS, write_player

__all__ = ["PLAYER_CSS", "PLAYER_JS", "write_player"]
