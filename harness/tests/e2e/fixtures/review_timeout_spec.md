# Requirements

Exercise harness resume behavior after a REVIEW timeout.

# Architecture

The generated fixture can remain trivial; the important behavior is the harness review state.

# Verification

A simulated REVIEW timeout must leave phase.status as building and review.status as error.
Resume must route back to REVIEWING without rebuilding completed tasks.

# Test Plan

Mock Claude REVIEW to timeout before Phase 3.

# Build Plan

## Phase 1: Project Setup

Create a minimal workspace.

## Phase 2: Review Timeout Path [python]

Complete all tasks, then simulate a REVIEW subprocess timeout.

