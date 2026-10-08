"""Hand a delivery CSV to the operator. Other tools stay redacted."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from pathlib import Path

FILENAME_RE = re.compile(
    r"^(series_ab|pe_partners)_enriched_\d+(_[A-Za-z0-9-]+)?_\d{4}-\d{2}-\d{2}_\d{6}\.csv$"
)
TTL_SECONDS = 15 * 60
SAVE_NOTE = "Save this file on your machine. Do not paste the list into chat."


def signing_secret() -> str:
    return (
        os.environ.get("MOBYDICK_DOWNLOAD_SECRET", "").strip()
        or os.environ.get("GETLEADS_API_KEY", "").strip()
        or os.environ.get("LEADMAGIC_API_KEY", "").strip()
    )


def signing_configured() -> bool:
    return bool(signing_secret())


def public_base_url() -> str:
    explicit = os.environ.get("MOBYDICK_PUBLIC_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if not domain:
        return ""
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}"


def signature(filename: str, exp: int, secret: str | None = None) -> str:
    key = secret if secret is not None else signing_secret()
    message = f"{filename}:{int(exp)}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def signed_path(filename: str, *, now: int | None = None) -> str:
    stamp = int(time.time()) if now is None else int(now)
    exp = stamp + TTL_SECONDS
    sig = signature(filename, exp)
    return f"/deliveries/{filename}?exp={exp}&sig={sig}"


def signed_url(filename: str, *, now: int | None = None) -> str:
    if not signing_configured():
        return ""
    path = signed_path(filename, now=now)
    base = public_base_url()
    return f"{base}{path}" if base else path


def signature_status(filename: str, exp: str, sig: str, *, now: int | None = None) -> str:
    """ok, bad, expired, or unconfigured."""
    secret = signing_secret()
    if not secret:
        return "unconfigured"
    if not str(exp).isdigit():
        return "bad"
    exp_i = int(exp)
    current = int(time.time()) if now is None else int(now)
    if exp_i < current:
        return "expired"
    expected = signature(filename, exp_i, secret)
    given = sig or ""
    if len(expected) != len(given):
        return "bad"
    if not hmac.compare_digest(expected, given):
        return "bad"
    return "ok"


def safe_filename(filename: str) -> str:
    name = Path(filename or "").name
    if not name or name != (filename or "").strip() or not FILENAME_RE.fullmatch(name):
        raise ValueError("delivery filename is not a Moby Dick CSV")
    return name


def resolve_filename(
    job_id: str = "",
    filename: str = "",
    *,
    job_status: str | None = None,
    job_csv_name: str | None = None,
) -> str:
    if (job_id or "").strip():
        if job_status not in {"completed", "completed_partial"}:
            raise ValueError("job is not completed")
        name = Path(job_csv_name or "").name
        if not name:
            raise ValueError("job has no delivery file")
        if filename and Path(filename).name != name:
            raise ValueError("filename does not match the job delivery")
        return safe_filename(name)
    if not (filename or "").strip():
        raise ValueError("job_id or filename is required")
    return safe_filename(filename)


def delivery_path(deliveries_dir: Path, filename: str) -> Path:
    name = safe_filename(filename)
    root = deliveries_dir.resolve()
    path = (root / name).resolve()
    if path.parent != root:
        raise ValueError("delivery filename is not a Moby Dick CSV")
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def build_delivery_download(
    *,
    job_id: str = "",
    filename: str = "",
    deliveries_dir: Path,
    job_status: str | None = None,
    job_csv_name: str | None = None,
    now: int | None = None,
) -> dict[str, object]:
    name = resolve_filename(
        job_id,
        filename,
        job_status=job_status,
        job_csv_name=job_csv_name,
    )
    path = delivery_path(deliveries_dir, name)
    text = path.read_text(encoding="utf-8")
    url = signed_url(name, now=now)
    return {
        "ok": True,
        "filename": name,
        "bytes": path.stat().st_size,
        "expires_in_seconds": TTL_SECONDS if url else None,
        "download_url": url,
        "csv_text": text,
        "note": SAVE_NOTE,
    }


def build_http_download(
    filename: str,
    exp: str,
    sig: str,
    *,
    deliveries_dir: Path,
    now: int | None = None,
) -> tuple[int, str, dict[str, str]]:
    """Status, body, headers for GET /deliveries/{filename}."""
    status = signature_status(filename, exp, sig, now=now)
    if status == "unconfigured":
        return 503, "download signing is not configured", {"Content-Type": "text/plain; charset=utf-8"}
    try:
        name = safe_filename(filename)
    except ValueError:
        return 404, "delivery not found", {"Content-Type": "text/plain; charset=utf-8"}
    if status == "expired":
        return 410, "download link expired", {"Content-Type": "text/plain; charset=utf-8"}
    if status != "ok":
        return 403, "invalid download link", {"Content-Type": "text/plain; charset=utf-8"}
    try:
        path = delivery_path(deliveries_dir, name)
    except (FileNotFoundError, ValueError):
        return 404, "delivery not found", {"Content-Type": "text/plain; charset=utf-8"}
    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{name}"',
    }
    return 200, path.read_text(encoding="utf-8"), headers
