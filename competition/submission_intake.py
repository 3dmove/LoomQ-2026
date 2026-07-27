#!/usr/bin/env python3
"""Validate one Issue Form submission, archive it, and publish its receipt."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from competition.submission_common import (  # noqa: E402
    COMMIT_RE,
    RECEIPT_MARKER,
    GitHubAPIError,
    GitHubClient,
    SubmissionError,
    isoformat_z,
    load_json,
    normalize_repository_url,
    parse_issue_body,
    parse_timestamp,
    sha256_file,
    utc_now,
    validate_team_id,
)


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "competition" / "config.json"
LABELS = {
    "submission:accepted": ("1a7f37", "Validated and archived final submission"),
    "submission:rejected": ("b42318", "Submission failed automatic intake validation"),
}


def api_path(full_name: str, suffix: str) -> str:
    owner, repo = full_name.split("/", 1)
    base = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    return base if not suffix else f"{base}/{suffix.lstrip('/')}"


def append_output(path: str | None, **values: str) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def validate_issue(
    event: dict[str, Any],
    config: dict[str, Any],
    client: GitHubClient,
    archive: Path,
) -> dict[str, Any]:
    issue = event.get("issue") or {}
    issue_number = int(issue.get("number", 0))
    if issue_number <= 0:
        raise RuntimeError("event does not contain a valid issue number")
    created_at = parse_timestamp(str(issue.get("created_at", "")))
    deadline = parse_timestamp(config["deadline"])
    if created_at > deadline:
        raise SubmissionError(f"提交晚于截止时间 {config['deadline_display']}")

    fields = parse_issue_body(str(issue.get("body", "")))
    missing = [name for name in ("team_id", "repository", "commit_sha", "levels", "declarations") if not fields.get(name)]
    if missing:
        raise SubmissionError("提交表单缺少必填字段: " + ", ".join(missing))
    checked_declarations = re.findall(r"^- \[[xX]\] I agree\b", fields["declarations"], re.MULTILINE)
    if len(checked_declarations) != 3:
        raise SubmissionError("必须勾选所有原创性与评测授权声明")

    team_id = validate_team_id(fields["team_id"])
    actor = str(issue.get("user", {}).get("login", "")).lower()
    if team_id != actor:
        raise SubmissionError("Team ID 必须是 Issue 作者的 GitHub 用户名")

    full_name, canonical_url = normalize_repository_url(fields["repository"])
    owner = full_name.split("/", 1)[0].lower()
    if owner != actor:
        raise SubmissionError("fork 所有者必须与 Issue 作者是同一个 GitHub 账号")
    try:
        repository = client.json("GET", api_path(full_name, ""))
    except GitHubAPIError as exc:
        if exc.status == 404:
            raise SubmissionError("fork 仓库不存在或不可读") from exc
        raise
    source = str((repository.get("source") or {}).get("full_name", ""))
    if not repository.get("fork") or source.lower() != config["upstream"].lower():
        raise SubmissionError(f"仓库必须位于 {config['upstream']} 的 fork network")

    commit_sha = fields["commit_sha"].strip().lower()
    if not COMMIT_RE.fullmatch(commit_sha):
        raise SubmissionError("Commit SHA 必须是 40 位完整十六进制字符")
    try:
        commit = client.json("GET", api_path(full_name, f"commits/{commit_sha}"))
    except GitHubAPIError as exc:
        if exc.status == 404:
            raise SubmissionError("Commit SHA 在该 fork 中不存在") from exc
        raise
    if str(commit.get("sha", "")).lower() != commit_sha:
        raise SubmissionError("GitHub 返回的 commit 与提交 SHA 不一致")

    for required in config["required_files"]:
        quoted_path = "/".join(urllib.parse.quote(part) for part in required.split("/"))
        try:
            content = client.json("GET", api_path(full_name, f"contents/{quoted_path}?ref={commit_sha}"))
        except GitHubAPIError as exc:
            if exc.status == 404:
                raise SubmissionError(f"指定 SHA 缺少必需文件: {required}") from exc
            raise
        if not isinstance(content, dict) or content.get("type") != "file":
            raise SubmissionError(f"必需路径不是普通文件: {required}")

    client.download(
        api_path(full_name, f"tarball/{commit_sha}"),
        archive,
        int(config["max_archive_bytes"]),
    )
    archive_sha256 = sha256_file(archive)
    artifact_name = f"submission-{team_id}-issue-{issue_number}"
    return {
        "schema_version": "1.0",
        "team_id": team_id,
        "repository": canonical_url,
        "repository_full_name": full_name,
        "commit_sha": commit_sha,
        "levels": fields["levels"],
        "hardware_evidence": fields.get("hardware_evidence", ""),
        "issue_number": issue_number,
        "issue_url": issue.get("html_url", ""),
        "issue_author": actor,
        "issue_created_at": isoformat_z(created_at),
        "archive_sha256": archive_sha256,
        "archive_bytes": archive.stat().st_size,
        "artifact_name": artifact_name,
        "submission_path": config["submission_path"],
    }


def ensure_label(client: GitHubClient, upstream: str, name: str) -> None:
    color, description = LABELS[name]
    try:
        client.json("POST", api_path(upstream, "labels"), {"name": name, "color": color, "description": description})
    except GitHubAPIError as exc:
        if exc.status != 422:
            raise


def finish_issue(client: GitHubClient, upstream: str, issue_number: int, label: str, body: str) -> None:
    ensure_label(client, upstream, label)
    client.json("POST", api_path(upstream, f"issues/{issue_number}/labels"), {"labels": [label]})
    client.json("POST", api_path(upstream, f"issues/{issue_number}/comments"), {"body": body})
    client.json("PATCH", api_path(upstream, f"issues/{issue_number}"), {"state": "closed"})
    client.json("PUT", api_path(upstream, f"issues/{issue_number}/lock"), {"lock_reason": "resolved"})


def reject_issue(client: GitHubClient, config: dict[str, Any], issue_number: int, reason: str) -> None:
    body = (
        "## ❌ 提交未通过自动校验\n\n"
        f"{reason}\n\n"
        "Issue 内容不可编辑后重用；请修复后重新创建“最终提交” Issue。"
    )
    finish_issue(client, config["upstream"], issue_number, "submission:rejected", body)


def validate_command(args: argparse.Namespace) -> int:
    config = load_json(Path(args.config))
    event = load_json(Path(args.event))
    issue_number = int(event.get("issue", {}).get("number", 0))
    client = GitHubClient(os.environ["GH_TOKEN"])
    try:
        metadata = validate_issue(event, config, client, Path(args.archive))
    except SubmissionError as exc:
        reject_issue(client, config, issue_number, str(exc))
        append_output(args.github_output, eligible="false")
        print(f"submission rejected: {exc}")
        return 0
    Path(args.metadata).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_output(
        args.github_output,
        eligible="true",
        artifact_name=metadata["artifact_name"],
        retention_days=str(config["artifact_retention_days"]),
    )
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


def finalize_command(args: argparse.Namespace) -> int:
    config = load_json(Path(args.config))
    metadata = load_json(Path(args.metadata))
    artifact_id = int(args.artifact_id)
    if artifact_id <= 0:
        raise RuntimeError("upload-artifact did not return a valid artifact ID")
    receipt = dict(metadata)
    receipt["artifact_id"] = artifact_id
    receipt["accepted_at"] = isoformat_z(utc_now())
    receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    body = (
        "## ✅ 提交已校验并归档\n\n"
        f"- Team: `{receipt['team_id']}`\n"
        f"- Commit: `{receipt['commit_sha']}`\n"
        f"- Archive SHA-256: `{receipt['archive_sha256']}`\n"
        f"- Artifact ID: `{artifact_id}`\n\n"
        "同队伍如需更新，请重新创建最终提交 Issue；截止前最后一次有效提交生效。\n\n"
        f"<!-- {RECEIPT_MARKER}\n{receipt_json}\n-->"
    )
    client = GitHubClient(os.environ["GH_TOKEN"])
    finish_issue(
        client,
        config["upstream"],
        int(metadata["issue_number"]),
        "submission:accepted",
        body,
    )
    print(receipt_json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LoomQ GitHub Issue submission intake")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--event", required=True)
    validate.add_argument("--archive", required=True)
    validate.add_argument("--metadata", required=True)
    validate.add_argument("--github-output")
    validate.add_argument("--config", default=str(CONFIG))
    validate.set_defaults(function=validate_command)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--metadata", required=True)
    finalize.add_argument("--artifact-id", required=True)
    finalize.add_argument("--config", default=str(CONFIG))
    finalize.set_defaults(function=finalize_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.function(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"submission intake failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
