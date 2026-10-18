# ring_filter: insider-ring cluster rule (read-only, stdlib only)

Decides what a cluster (2+ watched wallets buying the same coin within 30 min) means when some wallets are known
insider rings from your own Rug Shield research.

| Cluster | Result |
| --- | --- |
| no ring wallets | `CLUSTER`, HIGH |
| ALL ring wallets | `RING_FLAG`, priority RISK, no owner ping; write to `ring_flags.ndjson` and post in the Trading Desk room as a RISK FLAG for Rug Shield |
| ring + independent STRONG/CONFIRMED | `CLUSTER` HIGH, `ring_rule: RING+STRONG`, tag "RING+STRONG: Rug Shield check now (ring rule)" |
| ring + independent not strong | `CLUSTER` HIGH, `ring_rule: RING+INDEPENDENT` |

`provisional_ring` wallets count as ring only next to a real `insider_ring` wallet. Ring wallets are never independent
confirmation. Rug Shield side: a coin whose deployer or first-block buyers trace to a ring is HIGH_RISK at best; REJECT if
proceeds sweep back to the ring funder.

```bash
python3 ring_filter.py --test
python3 ring_filter.py ../wallets.example.json "EXAMPLE_SOLANA_RING_WALLET_1,EXAMPLE_SOLANA_WALLET_1"
```
```python
from ring_filter import classify_cluster
classify_cluster(["A", "B"], {"A": {"insider_ring": "RING-1"}, "B": {"grade": "STRONG"}})
```
Flag only. It never acts, trades or posts.
