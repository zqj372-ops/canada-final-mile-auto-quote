# Product Requirements

## Goal

Build a Canada final-mile truck delivery quote module that produces fast,
traceable, deterministic prices and lets AI explain only locked quote results.

## Non-goals

- No AI-generated prices.
- No AI access to full Excel files or full rate cards.
- No invented market rates when the database has no match.
- No production carrier booking in the first MVP.

## MVP Scope

1. Import vendor rate cards, historical delivery rows, address risk rows, and fee configuration rows.
2. Normalize Canadian addresses, postal codes, province names, and FSA values.
3. Match shipments against deterministic rules in a fixed priority order.
4. Return cost, suggested selling price, confidence, matched rule, risk tags, and manual review flags.
5. Provide a small AI context that is price locked and validated after generation.

## First Release Boundary

The first release should prove that the system does not hallucinate prices. It
can use simple local inputs and test fixtures before a full PostgreSQL data
access layer is added.

