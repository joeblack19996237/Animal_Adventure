# Requirements

Build a mixed Python and TypeScript fixture for per-phase language routing.

# Architecture

Backend and frontend phases are separate so the harness can select phase-specific profiles.

# Verification

Verify harness language detection and phase routing only.

# Test Plan

Mock Claude responses for both language phases.

# Build Plan

## Phase 1: Project Setup

Prepare shared workspace structure.

## Phase 2: Backend API [python]

Implement a tiny backend endpoint.

## Phase 3: Frontend View [typescript]

Implement a tiny client view.

## Phase 4: Integration Testing

Exercise cross-stack integration routing.

