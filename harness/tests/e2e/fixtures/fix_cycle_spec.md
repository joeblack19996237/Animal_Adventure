# Requirements

Exercise BLOCK -> FIX -> targeted re-review behavior in the harness.

# Architecture

The fixture exists only to drive harness review/fix state transitions.

# Verification

Blocking HIGH issues require a targeted re-review before the phase can advance.

# Test Plan

Mock Claude REVIEW to block once, mock FIX to repair the issue, then mock targeted REVIEW to approve.

# Build Plan

## Phase 1: Project Setup

Create a minimal workspace.

## Phase 2: Blocking Fix Cycle [python]

Trigger a HIGH review issue and verify the fix cycle.

