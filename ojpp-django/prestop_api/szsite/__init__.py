"""Our own reader of SŽ's passenger site (potniski.sz.si): live trains, notices, works, platforms and train sets.

client.py clears Cloudflare's check once (FlareSolverr) and then makes small plain requests, parse.py reads the pages,
store.py keeps the last good copy of each, serve.py hands them to the API on 127.0.0.1 and jobs.py runs the schedule
(`manage.py szsite`). Spec part N-B5; docs/research/2026-11-05-sz-website-reader.md has the measurements.
"""
