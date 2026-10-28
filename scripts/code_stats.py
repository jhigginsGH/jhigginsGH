#!/usr/bin/env python3
"""Build the "code across all my repos" card (assets/code-stats.svg).

Runs locally with your existing `gh` login, so it can see private repos
without storing a token in GitHub. It:

1. lists every non-fork repo you own,
2. asks GitHub which commits on each default branch are attributed to you
   (so classmates' commits in group projects are not counted),
3. bare-clones each repo into a temp dir and sums the lines those commits
   added, per language, skipping lockfiles, generated/vendored folders and
   non-code files,
4. writes an SVG with the total and a language bar. Only totals and
   percentages are written, never repo names.

Usage: python3 scripts/code_stats.py [--debug]
"""

import collections
import json
import os
import subprocess
import sys
import tempfile

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "code-stats.svg")

# Extension -> (language, linguist color)
LANGUAGES = {
    ".java": ("Java", "#b07219"),
    ".py": ("Python", "#3572A5"),
    ".ts": ("TypeScript", "#3178c6"),
    ".tsx": ("TypeScript", "#3178c6"),
    ".mts": ("TypeScript", "#3178c6"),
    ".js": ("JavaScript", "#f1e05a"),
    ".jsx": ("JavaScript", "#f1e05a"),
    ".mjs": ("JavaScript", "#f1e05a"),
    ".cjs": ("JavaScript", "#f1e05a"),
    ".swift": ("Swift", "#F05138"),
    ".dart": ("Dart", "#00B4AB"),
    ".kt": ("Kotlin", "#A97BFF"),
    ".c": ("C", "#555555"),
    ".h": ("C", "#555555"),
    ".cpp": ("C++", "#f34b7d"),
    ".cc": ("C++", "#f34b7d"),
    ".hpp": ("C++", "#f34b7d"),
    ".lua": ("Lua", "#000080"),
    ".vim": ("Vim Script", "#199f4b"),
    ".html": ("HTML", "#e34c26"),
    ".css": ("CSS", "#663399"),
    ".scss": ("CSS", "#663399"),
    ".sh": ("Shell", "#89e051"),
    ".bash": ("Shell", "#89e051"),
    ".zsh": ("Shell", "#89e051"),
    ".sql": ("SQL", "#e38c00"),
    ".prisma": ("Prisma", "#0c344b"),
}

SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Podfile.lock",
    "pubspec.lock", "poetry.lock", "Cargo.lock", "Gemfile.lock",
    "mvnw", "mvnw.cmd", "gradlew", "gradlew.bat",
}
SKIP_DIRS = {
    "node_modules", "build", "dist", "out", "target", "bin", "obj",
    ".dart_tool", "Pods", ".gradle", ".idea", ".vscode", ".expo",
    "vendor", "venv", ".venv", "env", "__pycache__", "DerivedData",
    "generated", "Generated", ".mvn", "coverage", "migrations",
    "ephemeral", "Runner", "runner", "xcuserdata", "site-packages",
}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".g.dart", ".pb.go")


def run(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def gh_json(*args):
    return json.loads(run("gh", *args))


def language_for(path):
    parts = path.split("/")
    if parts[-1] in SKIP_FILES or any(p in SKIP_DIRS for p in parts[:-1]):
        return None
    if path.endswith(SKIP_SUFFIXES):
        return None
    return LANGUAGES.get(os.path.splitext(path)[1].lower())


def my_commits(full_name, login):
    shas = run(
        "gh", "api", "--paginate",
        f"repos/{full_name}/commits?author={login}&per_page=100",
        "--jq", ".[].sha",
    )
    return set(shas.split())


def count_repo(full_name, login, workdir, debug):
    shas = my_commits(full_name, login)
    if not shas:
        return collections.Counter(), []
    dest = os.path.join(workdir, full_name.replace("/", "__"))
    run("gh", "repo", "clone", full_name, dest, "--", "--bare", "--quiet")
    log = run("git", "log", "--no-merges", "--numstat", "--format=@%H", cwd=dest)
    per_lang = collections.Counter()
    per_commit = []
    sha, added_here = None, 0
    for line in log.splitlines():
        if line.startswith("@"):
            if sha in shas:
                per_commit.append((added_here, sha))
            sha, added_here = line[1:], 0
            continue
        if not line.strip() or sha not in shas:
            continue
        added, _deleted, path = line.split("\t", 2)
        if added == "-":  # binary
            continue
        if " => " in path:  # rename: count against the new path
            path = path.replace("{", "").replace("}", "").split(" => ")[-1]
        lang = language_for(path)
        if lang:
            per_lang[lang] += int(added)
            added_here += int(added)
    if sha in shas:
        per_commit.append((added_here, sha))
    if debug:
        biggest = sorted(per_commit, reverse=True)[:3]
        print(f"{full_name}: {sum(per_lang.values())} lines, biggest commits {biggest}", file=sys.stderr)
    return per_lang, per_commit


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(total, per_lang, repo_count):
    ranked = per_lang.most_common()
    top = ranked[:8]
    other = sum(v for _, v in ranked[8:])
    if other:
        top.append((("Other", "#8b949e"), other))
    width, pad, bar_w = 495, 25, 445
    rows = (len(top) + 1) // 2
    height = 130 + rows * 25

    segs, x = [], pad
    for i, ((name, color), n) in enumerate(top):
        w = bar_w * n / total if i < len(top) - 1 else pad + bar_w - x
        segs.append(f'<rect x="{x:.2f}" y="95" width="{w:.2f}" height="8" fill="{color}"/>')
        x += w

    legend = []
    for i, ((name, color), n) in enumerate(top):
        lx = pad + (i % 2) * 225
        ly = 130 + (i // 2) * 25
        pct = 100 * n / total
        legend.append(
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text x="{lx + 16}" y="{ly}" class="lang">{esc(name)} {pct:.1f}%</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{total:,} lines of code written across {repo_count} repos">
<style>
  .bg {{ fill: #ffffff; }}
  .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #F97316; }}
  .big {{ font: 700 26px 'Segoe UI', Ubuntu, Sans-Serif; fill: #24292f; }}
  .sub {{ font: 400 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: #57606a; }}
  .lang {{ font: 400 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #24292f; }}
  @media (prefers-color-scheme: dark) {{
    .bg {{ fill: #0d1117; }}
    .big, .lang {{ fill: #c9d1d9; }}
    .sub {{ fill: #8b949e; }}
  }}
</style>
<rect class="bg" x="0.5" y="0.5" rx="4.5" width="{width - 1}" height="{height - 1}"/>
<text x="{pad}" y="35" class="title">Code I've written</text>
<text x="{pad}" y="72" class="big">{total:,} lines<tspan class="sub" dx="12">across {repo_count} repos, public and private</tspan></text>
<mask id="bar"><rect x="{pad}" y="95" width="{bar_w}" height="8" rx="4" fill="white"/></mask>
<g mask="url(#bar)">{''.join(segs)}</g>
{''.join(legend)}
</svg>
"""


def main():
    debug = "--debug" in sys.argv
    login = run("gh", "api", "user", "--jq", ".login").strip()
    repos = gh_json("repo", "list", login, "--source", "--limit", "500", "--json", "nameWithOwner,isEmpty")
    totals = collections.Counter()
    counted = 0
    with tempfile.TemporaryDirectory() as workdir:
        for repo in repos:
            if repo["isEmpty"]:
                continue
            per_lang, _ = count_repo(repo["nameWithOwner"], login, workdir, debug)
            if per_lang:
                counted += 1
                totals.update(per_lang)
    total = sum(totals.values())
    if debug:
        for (name, _), n in totals.most_common():
            print(f"  {name}: {n}", file=sys.stderr)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(render(total, totals, counted))
    print(f"{total:,} lines across {counted} repos -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
