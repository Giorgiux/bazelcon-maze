#!/usr/bin/env bash
# Build metadata consumed via --workspace_status_command. STABLE_BUILD_TIME is
# compiled into the engine (see //engine) and shown on the game's title screen.
echo "STABLE_BUILD_TIME $(date -u +%Y-%m-%dT%H:%M:%SZ)"
