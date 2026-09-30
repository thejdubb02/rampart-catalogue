#!/usr/bin/env python3
"""Validate themes/ and templates/ and write a deterministic index.json."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 8 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
PLACEHOLDER_RE = re.compile(r"\{\{([^}]*)\}\}")
KNOWN_PLACEHOLDERS = {"name", "first name", "email", "subject", "me"}
AUTHOR = "Rampart"

THEME_COLOURS = (
    "background",
    "surface",
    "surfaceVariant",
    "selection",
    "text",
    "muted",
    "line",
    "accent",
    "onAccent",
)
THEME_KEYS = {"name", "dark", "description", "page", *THEME_COLOURS}
PAGE_KEYS = set(THEME_COLOURS)
TEMPLATE_KEYS = {"name", "subject", "body", "description"}
CONTRAST_PAIRS = (
    ("text", "background", 4.5),
    ("text", "surface", 4.5),
    ("muted", "background", 3.0),
    ("onAccent", "accent", 4.5),
)

ROOT = Path(__file__).resolve().parent.parent


class CatalogueError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def relative_luminance(colour: str) -> float:
    """WCAG 2 relative luminance, matching Rampart's contrastRatio."""
    raw = colour[1:]
    values = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def channel(value: float) -> float:
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in values)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    one = relative_luminance(first)
    two = relative_luminance(second)
    lighter = max(one, two)
    darker = min(one, two)
    return (lighter + 0.05) / (darker + 0.05)


def render_index(index: dict) -> str:
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def build_index(root: Path | str | None = None) -> dict:
    root = ROOT if root is None else Path(root)
    errors: list[str] = []
    items: list[dict] = []
    seen: dict[str, str] = {}

    for kind, folder in (("template", "templates"), ("theme", "themes")):
        directory = root / folder
        if not directory.is_dir():
            errors.append(f"missing {folder}/")
            continue
        for path in sorted(directory.iterdir(), key=lambda entry: entry.name):
            where = path.relative_to(root).as_posix()
            if not path.is_file() or path.suffix != ".json":
                errors.append(f"{where}: file name must be <id>.json")
                continue
            item_id = path.stem
            if ID_RE.fullmatch(item_id) is None:
                errors.append(f"{where}: id {item_id} does not match {ID_RE.pattern}")
            if item_id in seen:
                errors.append(f"{where}: id {item_id} is already used by {seen[item_id]}")
            else:
                seen[item_id] = where

            raw = path.read_bytes()
            file_errors: list[str] = []
            if len(raw) > MAX_BYTES:
                file_errors.append(f"{where}: file is {len(raw)} bytes, over the {MAX_BYTES} byte cap")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                file_errors.append(f"{where}: file is not UTF-8")
                errors.extend(file_errors)
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                file_errors.append(f"{where}: invalid JSON ({exc.msg})")
                errors.extend(file_errors)
                continue

            if kind == "theme":
                _check_theme(data, where, file_errors)
                preview = _theme_preview(data) if not file_errors else None
            else:
                _check_template(data, where, file_errors)
                preview = _template_preview(data) if not file_errors else None
            errors.extend(file_errors)
            if file_errors or preview is None or ID_RE.fullmatch(item_id) is None or seen.get(item_id) != where:
                continue
            items.append(
                {
                    "kind": kind,
                    "id": item_id,
                    "name": data["name"],
                    "description": data["description"],
                    "author": AUTHOR,
                    "path": where,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "preview": preview,
                }
            )

    if errors:
        raise CatalogueError(errors)
    items.sort(key=lambda item: (item["kind"], item["id"]))
    return {"version": 1, "items": items}


def _theme_preview(data: dict) -> dict:
    preview = {
        "dark": data["dark"],
        "background": data["background"],
        "surface": data["surface"],
        "text": data["text"],
        "accent": data["accent"],
    }
    page = data.get("page")
    if isinstance(page, dict):
        preview["page"] = {
            "background": page["background"],
            "text": page["text"],
            "accent": page["accent"],
        }
    return preview


def _template_preview(data: dict) -> dict:
    body = data["body"] if isinstance(data.get("body"), str) else ""
    first = body.splitlines()[0] if body.splitlines() else ""
    return {"subject": data["subject"], "firstLine": first}


def _check_theme(data: object, where: str, errors: list[str]) -> None:
    if not isinstance(data, dict):
        errors.append(f"{where}: theme file must be a JSON object")
        return
    for key in sorted(set(data) - THEME_KEYS):
        errors.append(f"{where}: unknown field {key}")
    for key in ("name", "dark", "description"):
        if key not in data:
            errors.append(f"{where}: missing {key}")
    if "name" in data:
        _check_text(data["name"], f"{where}: name", errors)
    if "dark" in data and not isinstance(data["dark"], bool):
        errors.append(f"{where}: dark must be true or false")
    if "description" in data:
        _check_text(data["description"], f"{where}: description", errors)
        if isinstance(data["description"], str) and ("\n" in data["description"] or "\r" in data["description"]):
            errors.append(f"{where}: description must be one line")
    _check_colours(data, where, errors)
    if "page" in data:
        _check_page(data, where, errors)


def _check_page(data: dict, where: str, errors: list[str]) -> None:
    if data.get("dark") is not True:
        errors.append(f"{where}: page is only allowed when dark is true")
    page = data["page"]
    page_where = f"{where} page"
    if not isinstance(page, dict):
        errors.append(f"{where}: page must be an object")
        return
    for key in sorted(set(page) - PAGE_KEYS):
        errors.append(f"{page_where}: unknown field {key}")
    _check_colours(page, page_where, errors)
    background = page.get("background")
    if isinstance(background, str) and HEX_RE.fullmatch(background):
        luminance = relative_luminance(background)
        if luminance <= 0.5:
            errors.append(
                f"{page_where}: background luminance is {luminance:.2f}, needs to be over 0.5"
            )


def _check_template(data: object, where: str, errors: list[str]) -> None:
    if not isinstance(data, dict):
        errors.append(f"{where}: template file must be a JSON object")
        return
    for key in sorted(set(data) - TEMPLATE_KEYS):
        errors.append(f"{where}: unknown field {key}")
    for key in ("name", "subject", "body", "description"):
        if key not in data:
            errors.append(f"{where}: missing {key}")
    if "name" in data:
        _check_text(data["name"], f"{where}: name", errors)
    if "subject" in data:
        _check_text(data["subject"], f"{where}: subject", errors)
        if isinstance(data["subject"], str) and ("\n" in data["subject"] or "\r" in data["subject"]):
            errors.append(f"{where}: subject must be one line")
    body = data.get("body")
    if "body" in data and (not isinstance(body, str) or not body.strip()):
        errors.append(f"{where}: body must be a non-empty string")
    if "description" in data:
        _check_text(data["description"], f"{where}: description", errors)
        if isinstance(data["description"], str) and ("\n" in data["description"] or "\r" in data["description"]):
            errors.append(f"{where}: description must be one line")
    subject = data["subject"] if isinstance(data.get("subject"), str) else ""
    body_text = body if isinstance(body, str) else ""
    for match in PLACEHOLDER_RE.finditer(subject + "\n" + body_text):
        name = match.group(1).strip()
        if name not in KNOWN_PLACEHOLDERS:
            token = "{{" + name + "}}"
            errors.append(f"{where}: unknown placeholder {token}")


def _check_text(value: object, where: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where} must be a non-empty string")


def _check_colours(data: dict, where: str, errors: list[str]) -> None:
    for key in THEME_COLOURS:
        if key not in data:
            errors.append(f"{where}: missing {key}")
            continue
        value = data[key]
        if not isinstance(value, str) or HEX_RE.fullmatch(value) is None:
            errors.append(f"{where}: {key} is not #RRGGBB ({value!r})")
    for foreground, background, need in CONTRAST_PAIRS:
        ratio = _pair_contrast(data, foreground, background)
        if ratio is None:
            continue
        if ratio < need:
            errors.append(f"{where}: {foreground} on {background} contrast is {ratio:.2f}, needs {need:.1f}")


def _pair_contrast(data: dict, foreground: str, background: str) -> float | None:
    first = data.get(foreground)
    second = data.get(background)
    if not isinstance(first, str) or not isinstance(second, str):
        return None
    if HEX_RE.fullmatch(first) is None or HEX_RE.fullmatch(second) is None:
        return None
    return contrast_ratio(first, second)


def main(root: Path | str | None = None) -> int:
    root_path = ROOT if root is None else Path(root)
    try:
        index = build_index(root_path)
    except CatalogueError as error:
        print(error, file=sys.stderr)
        return 1
    text = render_index(index)
    (root_path / "index.json").write_bytes(text.encode("utf-8"))
    print(f"wrote index.json ({len(index['items'])} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
