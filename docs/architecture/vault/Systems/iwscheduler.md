---
canonical_id: "iwscheduler"
kind: system
layer: execution
currentness: same-file-bytes
runtime_observed: false
certified: false
---
# Installed profile dependency schedule

[[Layers/execution]] · [[Views/Full_Architecture]]

## Purpose

Runs state producers, builders, general controls, outage and late-card profiles in fixed order.

## Historical source state

Profile results, skips and progress records.

## Limits and unknowns

Health is usually absence of errors; ignored baseline failures and uncancelled timed work can cross boundaries.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S669]] — same-file-bytes
- [[Evidence/S680]] — same-file-bytes

## Directed relationships

- [[Systems/iwtimeout]] — bounds selected profile awaits (`E1565`)
- [[Systems/iwprojects]] — runs initial project producer (`E1571`)
- [[Systems/iwconfig]] — runs reversible configuration producer (`E1572`)
- [[Systems/iwsetup]] — creates setup and candidates (`E1574`)
- [[Systems/iwknowledge]] — runs canonical lifecycle (`E1579`)
- [[Systems/iwlearning]] — runs learning transition fixture (`E1580`)
- [[Systems/iwcoord]] — runs plan memory and context operations (`E1582`)
- [[Systems/iwquery]] — runs query and paging profiles (`E1583`)
- [[Systems/iwsynthetic]] — seeds conditional observation cases (`E1584`)
- [[Systems/iwsidebar]] — reconstructs preferences and outage (`E1587`)
- [[Systems/iwcleanup]] — runs cleanup receipt scenario (`E1589`)
- [[Systems/iwenvironment]] — runs environment fixture round trip (`E1590`)
- [[Systems/iwenterprise]] — runs pack and team fixtures (`E1591`)
- [[Systems/iwplugin]] — runs native plugin lifecycle (`E1593`)
- [[Systems/iwvalidation]] — invokes validation or refusal profile (`E1597`)
- [[Systems/iwbuilder]] — inspects general builders after producers (`E1598`)
- [[Systems/iwgeneral]] — runs general installed control probe (`E1600`)
- [[Systems/iwlate]] — runs physical and synthetic late-card producers (`E1603`)
