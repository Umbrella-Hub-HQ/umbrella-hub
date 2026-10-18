#!/usr/bin/env python3
"""Offline test for tg_watch source_groups (no network). Run: python3 tools/tg_watch/test_source_groups.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_watch as t
def high(prior, own, c): return bool(t.independent_groups(prior, own, c))
empty = {"source_groups": {}}
assert high(["ChanA"], "ChanB", empty), "empty groups: two different channels must be HIGH"
assert high(["ChanA", "ChanB"], "ChanC", empty)
assert not high(["ChanA"], "ChanA", empty), "same channel never counts twice"
assert not high(["chana"], "ChanA", empty), "case-insensitive"
g = {"source_groups": {"ChanA": "G1", "ChanB": "G1"}}
assert not high(["ChanA"], "ChanB", g), "grouped mirrors count as one source"
assert high(["ChanA"], "ChanC", g)
print("ALL PASS")
