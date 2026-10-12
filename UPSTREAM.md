# OJPP source provenance

Imported 2026-10-09 from [derp-si/ojpp-django](https://gitlab.com/derp-si/ojpp-django), exact revision **c8d9a45700159a73b2265296acae23c16abfa6fb** (upstream commit date 2026-02-07).

The GitLab commit API returned the exact requested SHA. The approved archive contained 240 files and its SHA-256 was `c8e716ca6353a4d56b3fc0d6113ba31dcf1f2890fc8be6d87d4299b4f082d73b`. Machine-readable provenance lives in `upstream-manifest.json`; `../scripts/import-ojpp.py` reproduces verification and refuses to overwrite an existing fork.

The original [AGPL license](ojpp-django/LICENSE) and notices are preserved. Source files were imported as regular files, without an undocumented nested Git repository. Brezavta source was not copied. Its HTTP integration is a later task after verifying permitted service access.

The preserved `.gitmodules` declares optional/source-generation inputs `slo_scrap`, `NeTEx` and `SIRI`. GitLab archives do not resolve gitlinks. Those submodule inputs were not downloaded; their exact revisions, licenses and runtime necessity must be checked before enabling source-generation or adapters that depend on them.

This is a **source import, not a running or production-ready backend**. The upstream Pipfile and lockfile are preserved as evidence; they pin Django 4.2 and older packages. Compatibility/security upgrades require tests before deployment. Upstream settings also require IJPP/LPP configuration even when only public HTTP reads are desired. The planned settings overlay must separate configured ingestion feeds from the API worker and remove credential assumptions from API-only startup.

Backend Task 1 remains incomplete. No Docker runtime is installed in this session, as confirmed by the user. PostGIS/Redis startup, readiness tests, migrations, upstream-record preservation and collector replay have not run. The next runtime gate is a Docker-compatible environment; the browser's synthetic statistics are not persisted backend statistics.
