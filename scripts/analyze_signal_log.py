#!/usr/bin/env python3
"""Summarize the content-free auto-signal log (logs/auto_signal.log).

Usage:
    python scripts/analyze_signal_log.py logs/auto_signal.log [logs/auto_signal.log.1 ...]

Offline, standard library only. Reads lines containing ``AUTOSIGNAL `` followed
by a JSON object; everything else is skipped. Exits 0 on empty or garbage
input; exits 2 (with usage) only when no file argument is given.

It answers two separate questions about candidate conversation keys:
  (a) repeat rate of the first-message hash across distinct session hashes
      (high sharing means the first-message hash collides across unrelated
      sessions and is unsafe as a key);
  (b) constancy of the first-message hash across the main-thread turns of one
      session (subagents share the session id but start with a different first
      message, so they are excluded from the main figure).
"""

import json
import sys
from collections import Counter, defaultdict

MARKER = "AUTOSIGNAL "
TOP_N = 5


def load_records(paths):
    records = []
    skipped = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    idx = line.find(MARKER)
                    if idx < 0:
                        continue
                    try:
                        rec = json.loads(line[idx + len(MARKER) :])
                    except ValueError:
                        skipped += 1
                        continue
                    if isinstance(rec, dict):
                        records.append(rec)
                    else:
                        skipped += 1
        except (OSError, UnicodeError) as exc:
            print("warning: cannot read %s: %s" % (path, exc), file=sys.stderr)
    return records, skipped


def pct(part, whole):
    return "n/a" if not whole else "%.1f%%" % (100.0 * part / whole)


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def stats_line(values):
    nums = sorted(v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
    if not nums:
        return "n=0 (no data)"
    return "n=%d min=%s median=%s p90=%s max=%s" % (
        len(nums),
        nums[0],
        quantile(nums, 0.5),
        quantile(nums, 0.9),
        nums[-1],
    )


def section(title):
    print()
    print("== %s ==" % title)


def freq_section(title, records, key):
    section(title)
    counter = Counter()
    for rec in records:
        names = rec.get(key)
        if isinstance(names, list):
            counter.update(str(n) for n in set(names))
    if not counter:
        print("(none)")
        return
    for name, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-40s %6d  %s" % (name, count, pct(count, len(records))))


def presence_section(records):
    section("Effort and thinking presence (auto vs non-auto)")
    groups = (
        ("auto", [r for r in records if r.get("auto") is True]),
        ("non-auto", [r for r in records if r.get("auto") is not True]),
    )
    for label, recs in groups:
        total = len(recs)
        print("  %s: %d records" % (label, total))
        if not total:
            continue
        rows = (
            ("reasoning_effort set", sum(1 for r in recs if r.get("reasoning_effort") is not None)),
            ("output_config.effort set", sum(1 for r in recs if r.get("oc_effort") is not None)),
            ("thinking set", sum(1 for r in recs if r.get("think_type") is not None)),
            ("thinking budget set", sum(1 for r in recs if r.get("think_budget") is not None)),
            ("anthropic-beta header", sum(1 for r in recs if r.get("beta") is True)),
        )
        for name, count in rows:
            print("    %-28s %6d  %s" % (name, count, pct(count, total)))
        for key in ("reasoning_effort", "oc_effort", "think_type"):
            dist = Counter(str(r.get(key)) for r in recs if r.get(key) is not None)
            if dist:
                print("    %s values: %s" % (key, dict(sorted(dist.items()))))


def size_section(records):
    section("Size, tools and max_tokens")
    for label, key in (
        ("est_tokens", "est_tokens"),
        ("tools", "tools"),
        ("max_tokens", "max_tokens"),
    ):
        print("  %-12s %s" % (label, stats_line([r.get(key) for r in records])))


def tool_result_section(records):
    section("Tool-result share")
    count = sum(1 for r in records if r.get("last_tool_result") is True)
    print(
        "  last message is tool_result: %d of %d (%s)"
        % (count, len(records), pct(count, len(records)))
    )


def class_section(records):
    section("Request class and auxiliary/subagent share")
    dist = Counter(str(r.get("req_class")) for r in records if r.get("req_class") is not None)
    if dist:
        for name, count in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0])):
            print("  req_class %-12s %6d  %s" % (name, count, pct(count, len(records))))
    else:
        print("  req_class: not present in any record")
    aux = sum(
        1
        for r in records
        if r.get("agent") is True or r.get("req_class") in ("subagent", "auxiliary")
    )
    print(
        "  subagent/auxiliary (agent id or class): %d of %d (%s)"
        % (aux, len(records), pct(aux, len(records)))
    )


def constancy(by_session):
    """Return (sessions_with_2plus_turns, share_constant_text, distribution)."""
    multi = {sid: fms for sid, fms in by_session.items() if len(fms["turns"]) >= 2}
    dist = Counter(len(set(fms["turns"])) for fms in multi.values())
    constant = dist.get(1, 0)
    return len(multi), constant, dist


def key_section(records):
    section("Conversation key comparison (sid_hash vs fm_hash)")
    total = len(records)
    with_sid = sum(1 for r in records if r.get("sid_hash"))
    with_fm = sum(1 for r in records if r.get("fm_hash"))
    print("  sid_hash presence: %d of %d (%s)" % (with_sid, total, pct(with_sid, total)))
    print("  fm_hash presence:  %d of %d (%s)" % (with_fm, total, pct(with_fm, total)))
    both = [r for r in records if r.get("sid_hash") and r.get("fm_hash")]
    print(
        "  records with both hashes: %d (excluded: %d without both)"
        % (len(both), total - len(both))
    )

    print()
    print("  (a) Repeat rate: distinct sid_hash per fm_hash")
    sessions_by_fm = defaultdict(set)
    for r in both:
        sessions_by_fm[r["fm_hash"]].add(r["sid_hash"])
    all_sessions = set(r["sid_hash"] for r in both)
    shared_groups = {fm: sids for fm, sids in sessions_by_fm.items() if len(sids) > 1}
    shared_sessions = set()
    for sids in shared_groups.values():
        shared_sessions |= sids
    print(
        "    fm_hash groups: %d, with more than 1 session: %d"
        % (len(sessions_by_fm), len(shared_groups))
    )
    share_a = pct(len(shared_sessions), len(all_sessions))
    print(
        "    sessions whose fm_hash is shared: %d of %d (%s)"
        % (len(shared_sessions), len(all_sessions), share_a)
    )
    top = sorted(sessions_by_fm.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_N]
    for fm, sids in top:
        print("    top group fm_hash=%s sessions=%d" % (fm, len(sids)))

    print()
    print("  (b) Constancy: distinct fm_hash per sid_hash")
    results = {}
    for label, recs in (
        ("main-thread only (agent == false)", [r for r in both if r.get("agent") is not True]),
        ("all records (includes subagents)", both),
    ):
        by_session = defaultdict(lambda: {"turns": []})
        for r in recs:
            by_session[r["sid_hash"]]["turns"].append(r["fm_hash"])
        multi, constant, dist = constancy(by_session)
        results[label] = (multi, constant)
        print("    %s:" % label)
        print(
            "      sessions with 2+ turns: %d; exactly 1 distinct fm_hash: %d (%s)"
            % (multi, constant, pct(constant, multi))
        )
        print("      distribution of distinct counts: %s" % dict(sorted(dist.items())))

    print()
    main_multi, main_const = results["main-thread only (agent == false)"]
    constancy_ok = bool(main_multi) and main_const >= 0.95 * main_multi
    repeat_ok = bool(all_sessions) and len(shared_sessions) <= 0.05 * len(all_sessions)
    if not both:
        fm_verdict = "undetermined (no records with both hashes)"
    elif constancy_ok and repeat_ok:
        fm_verdict = "usable (constancy near 100%, repeat rate near 0%)"
    else:
        fm_verdict = "NOT shown to be usable (needs constancy near 100% and repeat rate near 0%)"
    print("  Verdict: fm_hash is %s" % fm_verdict)
    print("  Verdict: sid_hash key presence rate is %s" % pct(with_sid, total))


def main(argv):
    paths = argv[1:]
    if not paths:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        print("usage: analyze_signal_log.py FILE [FILE ...]", file=sys.stderr)
        return 2
    records, skipped = load_records(paths)
    print("Signal log summary")
    print(
        "  files: %d, records: %d, skipped invalid AUTOSIGNAL lines: %d"
        % (len(paths), len(records), skipped)
    )
    freq_section("Body field names", records, "body_fields")
    freq_section("Header names", records, "header_names")
    presence_section(records)
    size_section(records)
    tool_result_section(records)
    class_section(records)
    key_section(records)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
