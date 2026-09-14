---
canonical_id: "cli"
kind: system
layer: host
currentness: changed-file
runtime_observed: false
certified: false
---
# CLI and Studio dispatch

[[Layers/host]] · [[Views/Full_Architecture]]

## Purpose

Routes explicit commands into the corresponding runtime owner and enforces the Studio operation protocol.

## Historical source state

Command payload and response envelopes.

## Limits and unknowns

The CLI exposes multiple execution families; it is not one universal task loop.

## Historical suggested evolution

No autonomous adaptation established; changes require its declared caller or owner.

## Evidence scope

Historical source model; file hashes refreshed. Byte agreement does not prove current behavior. This note is not a repair-closure receipt.

- [[Evidence/S3107]] — changed-file
- [[Evidence/S1709]] — changed-file
- [[Evidence/S2151]] — same-file-bytes
- [[Evidence/S3143]] — same-file-bytes
- [[Evidence/S1503]] — same-file-bytes

## Directed relationships

- [[Systems/workspace]] — dispatches project operations (`E007`)
- [[Systems/agent]] — dispatches agent operations (`E008`)
- [[Systems/workflow]] — dispatches workflow operations (`E009`)
- [[Systems/knowledge]] — dispatches knowledge lifecycle (`E010`)
- [[Systems/learning]] — dispatches explicit learning transitions (`E011`)
- [[Systems/skillstudio]] — dispatches skill lifecycle (`E012`)
- [[Systems/cleanroom]] — exposes bounded control operations (`E145`)
- [[Systems/health]] — dispatches health evaluation requests (`E159`)
- [[Systems/declared]] — exposes explicit declared outcome calls (`E160`)
- [[Systems/lexicalnav]] — selects a bounded dependency working set (`E229`)
- [[Systems/processreceipt]] — dispatches supplied record and apply flag (`E250`)
- [[Systems/knowledgebrowse]] — returns knowledge controller browse state (`E262`)
- [[Systems/doctor]] — dispatches explicit diagnostic request (`E271`)
- [[Systems/exactharness]] — runs exact tool certification (`E307`)
- [[Systems/pythonsurface]] — classifies surfaces using exact tool result (`E308`)
- [[Systems/mapquerycache]] — queries directly without prior freshness gate (`E535`)
- [[Systems/frontierselect]] — dispatches explicit reasoning frontier action (`E543`)
- [[Systems/startupreads]] — invokes startup without current revision (`E608`)
- [[Systems/refinerynovelty]] — dispatches explicit classify and merge-plan payloads (`E678`)
- [[Systems/refinerymetrics]] — dispatches rankings and calibration mappings (`E679`)
- [[Systems/cognitiveindexowner]] — rebuilds index for status validation (`E707`)
- [[Systems/metacognition]] — dispatches named operation and input JSON (`E726`)
- [[Systems/failureattribution]] — reads flags and computes cause recommendation (`E742`)
- [[Systems/assuranceaxes]] — reads axes and maps admissibility to valid (`E743`)
- [[Systems/eventbuspublication]] — accepts bounded external event batch (`E760`)
- [[Systems/benchmarkfreeze]] — freezes checks or compares supplied profiles (`E763`)
- [[Systems/intakeclosureledger]] — opens snapshots closes or checks intake (`E768`)
- [[Systems/declaredplan]] — lists describes or plans declared outcomes (`E794`)
- [[Systems/declaredworddispatch]] — runs generic declared script helper (`E795`)
- [[Systems/toolsignalassessment]] — assesses optional tool signals (`E802`)
- [[Systems/toolintakepublish]] — scans or records project tool intake (`E803`)
- [[Systems/preflightstatic]] — claims certify stage for authoritative preflight (`E827`)
- [[Systems/independentgates]] — runs selected independent assurance gates (`E863`)
- [[Systems/nativecomparetrees]] — compares canonical and preserved package trees (`E883`)
- [[Systems/globalisolation]] — dispatches preview or apply (`E892`)
- [[Systems/globalrestore]] — dispatches restore action (`E897`)
- [[Systems/releasecampaignclaim]] — exposes stage claim (`E899`)
- [[Systems/releasecampaignfinish]] — passes owner result (`E902`)
- [[Systems/agencyreviewers]] — exposes agents route action (`E940`)
- [[Systems/agencyprompt]] — exposes explicit prompt compilation (`E941`)
- [[Systems/healthclaimderive]] — reads supplied claim file (`E970`)
- [[Systems/eventbuspublication]] — publishes validated event batch (`E985`)
- [[Systems/externalmetadata]] — dispatches metadata status search and hydration (`E1105`)
- [[Systems/externalstageplan]] — builds fresh plan for stage command (`E1107`)
- [[Systems/externalhookgate]] — evaluates hook profile and supplied evidence (`E1110`)
- [[Systems/externalsession]] — normalizes and compares portable sessions (`E1111`)
- [[Systems/externalroutes]] — ranks caller-supplied route measurements (`E1112`)
- [[Systems/securitymetadata]] — dispatches discovery and golden queries (`E1113`)
- [[Systems/securityauthority]] — wraps declaration decision in valid envelope (`E1114`)
- [[Systems/securitygraphslice]] — dispatches independent outgoing graph traversal (`E1117`)
- [[Systems/securityreference]] — dispatches independent reference archive read (`E1118`)
- [[Systems/securityfinding]] — dispatches finding shape check (`E1120`)
- [[Systems/certreadinessversions]] — dispatches release readiness assessment (`E1121`)
- [[Systems/exacttoolaggregate]] — dispatches exact tools certification (`E1125`)
- [[Systems/structuralaggregate]] — dispatches structure audit after hygiene preparation (`E1139`)
- [[Systems/doctorclicontract]] — dispatches Doctor with requested host contract (`E1147`)
- [[Systems/clicontractindex]] — parses one explicit command (`E1367`)
- [[Systems/cliorchestrationlease]] — claims selected operation ownership before dispatch (`E1368`)
- [[Systems/clilocalloader]] — enters four broken loader branches (`E1369`)
- [[Systems/clisectionexecution]] — dispatches section show status or run (`E1370`)
- [[Systems/cligroupexecution]] — dispatches group selection and execution (`E1371`)
- [[Systems/clireleaseclaimfinalizer]] — finishes or retains claimed stages (`E1381`)
- [[Systems/cliexitcontracts]] — renders final response after releasing ownership (`E1383`)
- [[Systems/clihardwarefingerprint]] — wraps hardware action in work admission (`E1384`)
- [[Systems/cliinputpublication]] — loads and publishes selected payloads (`E1386`)
- [[Systems/clicognitiveboundary]] — loads cognitive index and routes action (`E1389`)
- [[Systems/cachewalkcustody]] — prepares optional certification hygiene (`E1431`)
