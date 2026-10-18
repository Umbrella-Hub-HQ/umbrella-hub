#!/usr/bin/env python3
"""ring_filter.py: insider-ring cluster classifier (READ-ONLY, no network, stdlib only).

Generic, standalone copy of the ring rule used by the Umbrella wallet watcher (2026-10-17). It decides what a
"cluster" (2+ watched wallets buying the same coin within the cluster window, default 30 min) means once some of
those wallets are known insider rings.

Wallet records (see ../flywheel_watch/wallets.example.json):
  address, grade (CONFIRMED / STRONG / INFERENCE / UNKNOWN), insider_ring (ring id, e.g. "RING-EXAMPLE-1"),
  provisional_ring (ring id; counts as ring ONLY when a real insider_ring wallet is in the same cluster).

Rules (in order):
  1. No ring wallets in the cluster -> ordinary CLUSTER, priority HIGH, ring_rule None.
  2. ALL wallets are ring wallets -> RING_FLAG, priority RISK, notify False (no owner ping). Write it to
     ring_flags.ndjson for the Trading Desk room as a RISK FLAG for Rug Shield. Flag only, never act.
  3. Ring wallet(s) + >= 1 independent wallet graded STRONG/CONFIRMED -> CLUSTER HIGH, ring_rule "RING+STRONG",
     tag "RING+STRONG: Rug Shield check now (ring rule)".
  4. Ring wallet(s) + independent wallet(s) not graded strong -> CLUSTER HIGH, ring_rule "RING+INDEPENDENT".
Rug Shield side of the rule: a coin whose deployer or first-block buyers trace to a ring is HIGH_RISK at best, and
REJECT if proceeds sweep back to the ring funder. Ring wallets never count as independent confirmation.

Usage as a module:  from ring_filter import classify_cluster
CLI test:           python3 ring_filter.py --test
"""
from __future__ import annotations

import json
import sys

STRONG_GRADES = {"STRONG", "CONFIRMED"}
RING_STRONG_TAG = "RING+STRONG: Rug Shield check now (ring rule)"
RING_RISK_NOTE = ("RISK FLAG for Rug Shield (ring rule): every buyer in this cluster is an insider-ring wallet. "
                  "Deployer/first-block buyers tracing to a ring = HIGH_RISK at best; REJECT if proceeds go back to the "
                  "ring funder. Flag only, never act.")


def classify_cluster(wallets: list[str], info: dict[str, dict]) -> dict:
    """wallets: addresses in the cluster. info: address -> wallet record. Returns a dict with kind, priority,
    notify, ring_rule, tag, ring_wallets, independent_wallets, independent_strong, rings."""
    ring = sorted(a for a in wallets if info.get(a, {}).get("insider_ring"))
    if ring:  # provisional ring wallets join only next to a real ring wallet
        ring = sorted(set(ring) | {a for a in wallets if info.get(a, {}).get("provisional_ring")})
    indep = [a for a in wallets if a not in ring]
    strong = sorted(a for a in indep if str(info.get(a, {}).get("grade") or "").upper() in STRONG_GRADES)
    rings = sorted({info[a].get("insider_ring") or info[a].get("provisional_ring") for a in ring})
    out = dict(ring_wallets=ring, independent_wallets=indep, independent_strong=strong, rings=rings, tag=None)
    if ring and not indep:
        return dict(out, kind="RING_FLAG", priority="RISK", notify=False, ring_rule="RING_ONLY", for_room=True,
                    room_post_status="pending", note=RING_RISK_NOTE)
    if ring and strong:
        return dict(out, kind="CLUSTER", priority="HIGH", notify=True, ring_rule="RING+STRONG", tag=RING_STRONG_TAG)
    if ring:
        return dict(out, kind="CLUSTER", priority="HIGH", notify=True, ring_rule="RING+INDEPENDENT",
                    note="ring wallet(s) + independent wallet(s) not rated strong; Rug Shield check (ring rule)")
    return dict(out, kind="CLUSTER", priority="HIGH", notify=True, ring_rule=None)


def _test() -> None:
    info = {
        "R1": {"insider_ring": "RING-A", "grade": "INFERENCE"},
        "R2": {"insider_ring": "RING-A", "grade": "INFERENCE"},
        "P1": {"provisional_ring": "RING-A", "grade": "STRONG"},
        "S1": {"grade": "STRONG"},
        "C1": {"grade": "CONFIRMED"},
        "W1": {"grade": "INFERENCE"},
    }
    r = classify_cluster(["S1", "W1"], info); assert r["kind"] == "CLUSTER" and r["ring_rule"] is None, r
    r = classify_cluster(["R1", "R2"], info); assert r["kind"] == "RING_FLAG" and r["priority"] == "RISK" and not r["notify"], r
    r = classify_cluster(["R1", "P1"], info); assert r["kind"] == "RING_FLAG", r          # provisional joins the ring
    r = classify_cluster(["P1", "W1"], info); assert r["ring_rule"] is None, r             # provisional alone = not ring
    r = classify_cluster(["R1", "S1"], info); assert r["ring_rule"] == "RING+STRONG" and r["tag"] == RING_STRONG_TAG, r
    r = classify_cluster(["R1", "C1", "W1"], info); assert r["ring_rule"] == "RING+STRONG", r
    r = classify_cluster(["R1", "W1"], info); assert r["ring_rule"] == "RING+INDEPENDENT" and r["priority"] == "HIGH", r
    print("ring_filter selftest ok (7 cases)")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    elif len(sys.argv) == 3:  # ring_filter.py wallets.json "ADDR1,ADDR2"
        ws = json.load(open(sys.argv[1])).get("wallets", [])
        print(json.dumps(classify_cluster(sys.argv[2].split(","), {w["address"]: w for w in ws}), indent=1))
    else:
        print(__doc__)
