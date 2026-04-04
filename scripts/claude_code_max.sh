#!/bin/bash
# Claude Code mit Max Subscription (nicht API Key)
# Unset ANTHROPIC_API_KEY damit Claude Code Max nutzt statt API billing

unset ANTHROPIC_API_KEY
export PATH="$HOME/.local/bin:$PATH"

# Alle Args durchleiten
exec claude "$@"
