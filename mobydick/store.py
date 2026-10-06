"""Persist exclude lists and delivered CSVs. Same-day files also count."""

from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from mobydick.config import Settings, settings as default_settings
from mobydick.domains import domains_from_values, normalize_domain
from mobydick.schemas import columns_for

LIST_SERIES_AB = "series_ab"
LIST_PE = "pe_partners"
KNOWN_LISTS = (LIST_SERIES_AB, LIST_PE)

_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Store:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        self.settings.exclude_dir.mkdir(parents=True, exist_ok=True)
        self.settings.deliveries_dir.mkdir(parents=True, exist_ok=True)
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.settings.dossiers_dir.mkdir(parents=True, exist_ok=True)
        self._seed_list(LIST_SERIES_AB)
        self._seed_list(LIST_PE)

    def _exclude_path(self, list_name: str) -> Path:
        name = self._normalize_list(list_name)
        filename = "series_ab.json" if name == LIST_SERIES_AB else "pe.json"
        return self.settings.exclude_dir / filename

    def _normalize_list(self, list_name: str) -> str:
        raw = (list_name or LIST_SERIES_AB).strip().lower()
        aliases = {
            "series_ab": LIST_SERIES_AB,
            "series-ab": LIST_SERIES_AB,
            "founders": LIST_SERIES_AB,
            "saas": LIST_SERIES_AB,
            "pe": LIST_PE,
            "pe_partners": LIST_PE,
            "pe-partners": LIST_PE,
        }
        if raw not in aliases:
            raise ValueError(f"Unknown exclude list {list_name!r}. Use series_ab or pe_partners.")
        return aliases[raw]

    def _seed_list(self, list_name: str) -> None:
        path = self._exclude_path(list_name)
        if path.exists():
            return
        path.write_text(
            json.dumps(
                {"list": list_name, "updated_at": None, "domains": []},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _read_list(self, list_name: str) -> dict[str, Any]:
        path = self._exclude_path(list_name)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {"list": list_name, "domains": []}
        domains = domains_from_values([str(d) for d in data.get("domains") or []])
        removed = domains_from_values([str(d) for d in data.get("removed") or []])
        data["list"] = self._normalize_list(list_name)
        data["domains"] = domains
        data["removed"] = removed
        return data

    def _write_list(
        self,
        list_name: str,
        domains: Iterable[str],
        removed: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "list": self._normalize_list(list_name),
            "updated_at": utc_now(),
            "domains": sorted(domains_from_values(list(domains))),
            "removed": sorted(domains_from_values(list(removed or []))),
        }
        path = self._exclude_path(list_name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return payload

    def _effective_domains(self, data: dict[str, Any], list_name: str) -> set[str]:
        removed = set(data.get("removed") or [])
        return (set(data["domains"]) | self._same_day_domains(list_name)) - removed

    def exclude_count(self, list_name: str = LIST_SERIES_AB) -> dict[str, Any]:
        with _lock:
            data = self._read_list(list_name)
            same_day = self._same_day_domains(list_name)
            combined = self._effective_domains(data, list_name)
            return {
                "list": data["list"],
                "persisted": len(data["domains"]),
                "same_day_files": len(same_day),
                "removed": len(data.get("removed") or []),
                "effective": len(combined),
                "updated_at": data.get("updated_at"),
            }

    def exclude_domains(self, list_name: str = LIST_SERIES_AB) -> set[str]:
        with _lock:
            data = self._read_list(list_name)
            return self._effective_domains(data, list_name)

    def exclude_add(self, domains: list[str], list_name: str = LIST_SERIES_AB) -> dict[str, Any]:
        incoming = domains_from_values(domains)
        with _lock:
            data = self._read_list(list_name)
            before = set(data["domains"])
            after = before | set(incoming)
            removed = set(data.get("removed") or []) - set(incoming)
            written = self._write_list(list_name, after, removed)
            return {
                "list": written["list"],
                "added": len(after) - len(before),
                "skipped_already_present": len(set(incoming) & before),
                "total": len(after),
                "updated_at": written["updated_at"],
            }

    def exclude_remove(self, domains: list[str], list_name: str = LIST_SERIES_AB) -> dict[str, Any]:
        """Drop domains from the list. A removal also overrides same-day delivery files."""
        incoming = domains_from_values(domains)
        with _lock:
            data = self._read_list(list_name)
            before = set(data["domains"])
            removed = set(data.get("removed") or []) | set(incoming)
            after = before - set(incoming)
            written = self._write_list(list_name, after, removed)
            effective = (after | self._same_day_domains(list_name)) - removed
            return {
                "list": written["list"],
                "removed": len(set(incoming)),
                "total": len(after),
                "effective": len(effective),
                "updated_at": written["updated_at"],
            }

    def exclude_check(self, domains: list[str], list_name: str = LIST_SERIES_AB) -> dict[str, Any]:
        incoming = domains_from_values(domains)
        excluded = self.exclude_domains(list_name)
        hits = [d for d in incoming if d in excluded]
        misses = [d for d in incoming if d not in excluded]
        return {
            "list": self._normalize_list(list_name),
            "checked": len(incoming),
            "already_delivered": hits,
            "new": misses,
            "already_delivered_count": len(hits),
            "new_count": len(misses),
        }

    def exclude_import(self, path: str, list_name: str = LIST_SERIES_AB) -> dict[str, Any]:
        source = Path(path)
        if not source.exists():
            raise ValueError(f"Import path does not exist: {path}")
        domains: list[str] = []
        if source.suffix.lower() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                domains = [str(x) for x in payload]
            elif isinstance(payload, dict):
                raw = payload.get("domains") or payload.get("exclude") or []
                domains = [str(x) for x in raw]
            else:
                raise ValueError("JSON exclude file must be a list or {domains: [...]}")
        else:
            with source.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames:
                    field = next(
                        (
                            name
                            for name in (
                                "company_domain",
                                "domain",
                                "email_domain",
                                "website",
                            )
                            if name in reader.fieldnames
                        ),
                        None,
                    )
                    if field:
                        for row in reader:
                            domains.append(str(row.get(field) or ""))
                    else:
                        raise ValueError("CSV needs a company_domain or domain column")
                else:
                    handle.seek(0)
                    domains = [line.strip() for line in handle if line.strip()]
        return self.exclude_add(domains, list_name)

    def _same_day_domains(self, list_name: str) -> set[str]:
        stamp = today_stamp()
        prefix = "series_ab" if self._normalize_list(list_name) == LIST_SERIES_AB else "pe_partners"
        out: set[str] = set()
        for path in self.settings.deliveries_dir.glob("*.csv"):
            if stamp not in path.name or not path.name.startswith(prefix):
                continue
            out.update(self._domains_from_csv(path))
        return out

    def _domains_from_csv(self, path: Path) -> set[str]:
        out: set[str] = set()
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    domain = normalize_domain(row.get("company_domain") or row.get("domain"))
                    if domain:
                        out.add(domain)
        except OSError:
            return out
        return out

    def write_delivery(
        self,
        audience: str,
        rows: list[dict[str, Any]],
        *,
        label: str | None = None,
    ) -> Path:
        name = self._normalize_list(audience)
        prefix = "series_ab" if name == LIST_SERIES_AB else "pe_partners"
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        extra = f"_{label}" if label else ""
        path = self.settings.deliveries_dir / f"{prefix}_enriched_{len(rows)}{extra}_{stamp}.csv"
        columns = columns_for(name)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") or "" for col in columns})
        eligible = rows
        if name == LIST_PE:
            eligible = [row for row in rows if (row.get("person_verified") or "") == "yes"]
        domains = [
            normalize_domain(row.get("company_domain"))
            for row in eligible
            if normalize_domain(row.get("company_domain"))
        ]
        self.exclude_add(domains, name)
        return path

    def list_deliveries(self, limit: int = 20) -> list[dict[str, Any]]:
        files = sorted(
            self.settings.deliveries_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for path in files[:limit]:
            out.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        return out

    def write_dossier(self, slug: str, markdown: str, payload: dict[str, Any]) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug.lower())[:80]
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        md_path = self.settings.dossiers_dir / f"{safe}_{stamp}.md"
        json_path = self.settings.dossiers_dir / f"{safe}_{stamp}.json"
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        return md_path
