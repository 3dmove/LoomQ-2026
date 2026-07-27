#!/usr/bin/env python3
"""Shared, standard-library-only helpers for LoomQ submission intake."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


RECEIPT_MARKER = "loomq-submission-receipt:v1"
TEAM_ID_RE = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
FIELD_NAMES = {
    "Team ID": "team_id",
    "Fork repository": "repository",
    "Commit SHA": "commit_sha",
    "Levels": "levels",
    "Hardware evidence": "hardware_evidence",
    "Declarations": "declarations",
}


class SubmissionError(RuntimeError):
    """A participant-correctable submission validation error."""


class GitHubAPIError(RuntimeError):
    """An unexpected or inspectable GitHub API response."""

    def __init__(self, method: str, path: str, status: int, detail: str = ""):
        super().__init__(f"GitHub API {method} {path} failed: HTTP {status}: {detail}")
        self.status = status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_issue_body(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    matches = list(re.finditer(r"^### (.+?)\s*$", body or "", re.MULTILINE))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        key = FIELD_NAMES.get(heading)
        if not key:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        value = body[match.end():end].strip()
        if value in {"_No response_", "No response"}:
            value = ""
        fields[key] = value
    return fields


def normalize_repository_url(value: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise SubmissionError("fork 地址必须是 https://github.com/OWNER/REPO")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise SubmissionError("fork 地址必须精确指向一个 GitHub 仓库")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner + repo):
        raise SubmissionError("fork 地址包含非法字符")
    return f"{owner}/{repo}", f"https://github.com/{owner}/{repo}"


def validate_team_id(value: str) -> str:
    team_id = value.strip().lower()
    if not TEAM_ID_RE.fullmatch(team_id):
        raise SubmissionError("Team ID 必须是有效的 GitHub 用户名（1–39 位字母、数字或单个连字符）")
    return team_id


@dataclass
class GitHubClient:
    token: str
    api_url: str = "https://api.github.com"

    def _request(self, method: str, path: str, data: Any = None) -> urllib.request.Request:
        url = path if path.startswith("https://") else self.api_url.rstrip("/") + path
        payload = None if data is None else json.dumps(data).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "loomq-submission-intake/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=payload, headers=headers, method=method)

    def json(self, method: str, path: str, data: Any = None) -> Any:
        request = self._request(method, path, data)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise GitHubAPIError(method, path, exc.code, detail) from exc
        return json.loads(raw.decode("utf-8")) if raw else None

    def download(self, path: str, destination: Path, max_bytes: int) -> int:
        request = self._request("GET", path)
        total = 0
        try:
            with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise SubmissionError(f"归档超过大小限制 {max_bytes} bytes")
                    output.write(chunk)
        except urllib.error.HTTPError as exc:
            raise GitHubAPIError("GET", path, exc.code) from exc
        if total == 0:
            raise SubmissionError("归档文件为空")
        return total


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt_from_comments(comments: list[dict[str, Any]]) -> dict[str, Any]:
    pattern = re.compile(
        rf"<!--\s*{re.escape(RECEIPT_MARKER)}\s*(\{{.*?\}})\s*-->",
        re.DOTALL,
    )
    for comment in reversed(comments):
        author = str(comment.get("user", {}).get("login", "")).lower()
        if author != "github-actions[bot]":
            continue
        match = pattern.search(comment.get("body", ""))
        if match:
            return json.loads(match.group(1))
    raise SubmissionError("找不到可信的提交回执")


def select_latest_submissions(
    issues: list[dict[str, Any]],
    receipts: dict[int, dict[str, Any]],
    deadline: datetime,
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    selected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for issue in issues:
        if "pull_request" in issue:
            continue
        labels = {item.get("name") for item in issue.get("labels", [])}
        if "submission:accepted" not in labels:
            continue
        created = parse_timestamp(issue["created_at"])
        if created > deadline:
            continue
        receipt = receipts.get(int(issue["number"]))
        if not receipt:
            continue
        team_id = validate_team_id(str(receipt.get("team_id", "")))
        candidate_key = (created, int(issue["number"]))
        current = selected.get(team_id)
        if current:
            current_key = (parse_timestamp(current[0]["created_at"]), int(current[0]["number"]))
            if candidate_key <= current_key:
                continue
        selected[team_id] = (issue, receipt)
    return selected


def safe_extract_submission(
    archive: Path,
    destination: Path,
    submission_path: str,
    max_files: int,
    max_extracted_bytes: int,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[Path] = set()
    file_count = 0
    total_size = 0
    found = False
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            source_path = PurePosixPath(member.name)
            if source_path.is_absolute() or ".." in source_path.parts or len(source_path.parts) < 2:
                raise SubmissionError(f"归档路径不安全: {member.name}")
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise SubmissionError(f"归档包含不允许的文件类型: {member.name}")
            relative = PurePosixPath(*source_path.parts[1:])
            wanted = PurePosixPath(submission_path)
            if relative != wanted and wanted not in relative.parents:
                continue
            found = True
            tail = relative.relative_to(wanted)
            if str(tail) == ".":
                continue
            target = destination.joinpath(*tail.parts)
            resolved = target.resolve()
            if destination.resolve() not in resolved.parents:
                raise SubmissionError(f"归档路径越界: {member.name}")
            if target in seen:
                raise SubmissionError(f"归档包含重复路径: {member.name}")
            seen.add(target)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            file_count += 1
            total_size += member.size
            if file_count > max_files or total_size > max_extracted_bytes:
                raise SubmissionError("归档解包后超过文件数或大小限制")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise SubmissionError(f"无法读取归档成员: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, member.mode & 0o777)
    if not found:
        raise SubmissionError(f"归档中不存在 {submission_path}/")
