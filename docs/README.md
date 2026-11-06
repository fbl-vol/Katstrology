# Documentation

Choose the task you need; these guides describe supported behavior, not a work log.

| Task | Guide |
| --- | --- |
| Use conversations, people, charts and saved records | [Using Kat](using-kat.md) |
| Understand ownership and data flow | [Architecture](architecture/README.md) |
| Develop the browser and run isolated browser checks | [Frontend development](../web/README.md) |
| Set up the backend and CLI | [Backend development](../m2/README.md) |
| Run isolated suites and interpret receipts | [Synthetic validation](testing.md) |
| Understand archive, deletion and local recovery | [Archive and recovery](archive-and-recovery.md) |
| Understand provider reads, capacity and continuity | [Provider/context contracts](provider-and-context.md) |
| Check natal conventions and limitations | [Natal calculations](../m2/NATAL-CHART.md) |
| Check timing, return and relationship methods | [Advanced calculations](../m2/ADVANCED-TECHNIQUES.md) |
| Import, select, read and revoke reference editions | [Reference library](reference-library.md) |
| Understand reference provenance and coverage | [Reference sources](../m2/STARTER-SOURCES.md) |
| Evaluate retrieval and local model limits | [Reference evaluation](../m2/RAG-EVALUATION.md) |
| Reproduce numerical feasibility checks | [Probes](../probes/README.md) |
| Package, run and recover a deployment | [Deployment](../deploy/README.md) |
| Understand release automation and installed trust | [Release automation](../deploy/AUTOMATION.md) |
| Prepare an explicitly authorized schema transition | [Manual transitions](../deploy/MANUAL_TRANSITIONS.md) |
| Keep private material out of source | [Publication boundaries](PUBLICATION.md) |
| Check redistribution obligations | [License](../LICENSE), [third-party notices](../THIRD-PARTY-NOTICES.md) |

Validation uses owned synthetic fixtures. A passing local suite does not authorize
activation, publication, private-archive access or live-provider traffic. Follow
the selected guide's prerequisites and keep deployment authority separate from
source preparation.
