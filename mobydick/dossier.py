"""Whale gift dossier for one lower-middle-market PE prospect."""

from __future__ import annotations

from typing import Any

from mobydick.research.apify import linkedin_posts
from mobydick.research.extract import extract_person_fields, footprint_is_thin, llm_extract
from mobydick.research.taddy import search_episodes
from mobydick.research.web import gather_company_pages
from mobydick.research.youtube import talks_with_transcripts
from mobydick.store import Store, utc_now


def _gift_ideas(signals: dict[str, str], sources: list[str]) -> list[dict[str, Any]]:
    ideas: list[dict[str, Any]] = []
    quirk = (signals.get("quirk") or "").lower()
    causes = (signals.get("causes") or "").lower()
    hometown = signals.get("hometown") or ""
    receipt = sources[0] if sources else ""

    def idea(
        name: str,
        reason: str,
        buy: str,
        price: str,
        risk: str,
        cite: str,
    ) -> dict[str, Any]:
        return {
            "gift": name,
            "why": reason,
            "buy_link": buy,
            "approx_price_usd": price,
            "risks": risk,
            "receipt_url": cite or receipt,
            "receipt_note": "Cites the public source that made this gift relevant.",
        }

    if "book" in quirk or "read" in quirk:
        ideas.append(
            idea(
                "A first-edition or special-press copy of a book they named",
                "They talked publicly about a specific book. Send that book, not a generic business title.",
                "https://bookshop.org",
                "40-90",
                "Wrong edition or a title they only mentioned in passing can feel lazy.",
                receipt,
            )
        )
    if any(word in quirk for word in ("marathon", "ironman", "ultra", "run")):
        ideas.append(
            idea(
                "A quality recovery or training item around $100",
                "They have talked about endurance sport in public. Keep it useful, not logo-slapped.",
                "https://www.rei.com",
                "80-120",
                "Sizing risk. Do not send apparel unless a size is public, which it almost never is.",
                receipt,
            )
        )
    if any(word in causes for word in ("veteran", "military")):
        ideas.append(
            idea(
                "A donation-plus-note to a veterans group they have named",
                "They have spoken about service. A gift that honors that beats swag.",
                "https://www.iava.org",
                "100",
                "Do not invent a charity. Only use an org they named or clearly support.",
                receipt,
            )
        )
    if hometown:
        ideas.append(
            idea(
                f"A well-known specialty food or craft item from {hometown}",
                "They have said where they are from. A hometown craft item is personal without being creepy.",
                "https://www.goldbelly.com",
                "70-110",
                "Skip alcohol unless they have talked about drinking that thing in public.",
                receipt,
            )
        )
    if not ideas:
        ideas.append(
            idea(
                "Hold the gift. Research is too thin.",
                "No identity signal strong enough for a $100 personal gift. Cut bait rather than send a generic object.",
                "",
                "",
                "A generic gift after thin research reads as creepy or lazy.",
                receipt,
            )
        )
    return ideas[:3]


def build_dossier(
    full_name: str,
    firm: str,
    *,
    title: str = "",
    linkedin_url: str = "",
    company_website: str = "",
    company_domain: str = "",
    use_apify: bool = False,
    store: Store | None = None,
) -> dict[str, Any]:
    pages = gather_company_pages(company_website, company_domain)
    talks = talks_with_transcripts(full_name, firm, max_videos=3)
    episodes = search_episodes(f"{full_name} {firm}".strip())
    apify_items: list[dict[str, Any]] = []
    if use_apify and linkedin_url:
        apify_items = linkedin_posts(linkedin_url)

    sources: list[dict[str, Any]] = []
    for page in pages.get("pages") or []:
        sources.append({"url": page.get("url"), "text": page.get("text")})
    for talk in talks:
        sources.append(
            {
                "url": talk.get("url"),
                "text": talk.get("transcript") or talk.get("description"),
                "has_transcript": talk.get("has_transcript"),
            }
        )
    for ep in episodes:
        sources.append(
            {
                "url": ep.get("audioUrl"),
                "text": f"{ep.get('name')} {ep.get('description')}",
                "podcast": ep.get("podcast"),
            }
        )

    thin = footprint_is_thin(sources)
    signals = extract_person_fields(full_name, firm, sources, audience="pe_partners")
    source_urls = [s.get("url") for s in sources if s.get("url")]
    gifts = _gift_ideas(signals, [u for u in source_urls if u])

    cut_bait = thin and not (signals.get("hometown") or signals.get("quirk") or signals.get("why"))
    confidence = "low" if cut_bait else signals.get("confidence") or "medium"

    gift_prompt = (
        f"You are writing a Moby Dick whale dossier for {full_name} at {firm}. "
        "Josh style: no em dashes, short one-line paragraphs. Research only. "
        "If signals are thin, say cut bait. Return JSON with judge_notes (string)."
    )
    llm = llm_extract(gift_prompt) or {}
    judge = str(llm.get("judge_notes") or "")
    if cut_bait and not judge:
        judge = "Footprint is mostly a LinkedIn profile. Cut bait. Do not send a gift."

    payload = {
        "company": firm,
        "decision_maker": {
            "full_name": full_name,
            "title": title,
            "linkedin_url": linkedin_url,
        },
        "office_ship_to": pages.get("mailing_address") or "",
        "footprint": {
            "company_pages": len(pages.get("pages") or []),
            "youtube_talks": len(talks),
            "talks_with_transcript": sum(1 for t in talks if t.get("has_transcript")),
            "podcast_episodes": len(episodes),
            "apify_posts": len(apify_items),
            "thin": thin,
            "cut_bait": cut_bait,
        },
        "personal_signals": {
            "hometown_or_from": signals.get("hometown") or "",
            "why_got_into_pe": signals.get("why") or "",
            "beliefs_or_causes": signals.get("causes") or "",
            "quirky_personal_fact": signals.get("quirk") or "",
            "best_emotional_hook": signals.get("hook") or "",
            "sources": source_urls,
        },
        "gift_ideas": gifts,
        "confidence": confidence,
        "judge_notes": judge,
        "research_note": "Public sources only. Never contacted. Blank means not found.",
        "created_at": utc_now(),
    }

    markdown = render_dossier(payload)
    path = None
    if store is not None:
        path = store.write_dossier(f"{full_name}-{firm}", markdown, payload)
        payload["path"] = str(path)
    payload["markdown"] = markdown
    return payload


def render_dossier(payload: dict[str, Any]) -> str:
    dm = payload.get("decision_maker") or {}
    signals = payload.get("personal_signals") or {}
    footprint = payload.get("footprint") or {}
    lines = [
        f"# Whale dossier: {dm.get('full_name') or 'Unknown'} / {payload.get('company') or ''}",
        "",
        "## 1. Company",
        str(payload.get("company") or ""),
        "",
        "## 2. Decision-maker",
        f"{dm.get('full_name') or ''} {('· ' + dm['title']) if dm.get('title') else ''}".strip(),
        dm.get("linkedin_url") or "",
        "",
        "## 3. Office ship-to address",
        payload.get("office_ship_to") or "Not found. Public office address only. Never invent. Never use a home address.",
        "",
        "## 4. Footprint",
        (
            f"Company pages {footprint.get('company_pages', 0)}. "
            f"YouTube talks {footprint.get('youtube_talks', 0)} "
            f"({footprint.get('talks_with_transcript', 0)} with transcript). "
            f"Podcast hits {footprint.get('podcast_episodes', 0)}."
        ),
        "Cut bait." if footprint.get("cut_bait") else "Enough public footprint to keep going.",
        "",
        "## 5. Personal signals",
        f"Hometown / from: {signals.get('hometown_or_from') or 'not stated'}",
        f"Why PE: {signals.get('why_got_into_pe') or 'not stated'}",
        f"Causes: {signals.get('beliefs_or_causes') or 'not stated'}",
        f"Quirk: {signals.get('quirky_personal_fact') or 'not stated'}",
        f"Best hook: {signals.get('best_emotional_hook') or 'not stated'}",
        "Sources:",
    ]
    for url in signals.get("sources") or []:
        lines.append(f"- {url}")
    lines += ["", "## 6. Gift ideas (~$100)"]
    for index, gift in enumerate(payload.get("gift_ideas") or [], start=1):
        lines += [
            f"### {index}. {gift.get('gift')}",
            gift.get("why") or "",
            f"Buy: {gift.get('buy_link') or 'n/a'}",
            f"Price: {gift.get('approx_price_usd') or 'n/a'}",
            f"Risks: {gift.get('risks') or ''}",
            f"Receipt: {gift.get('receipt_url') or ''} {gift.get('receipt_note') or ''}",
            "",
        ]
    lines += [
        "## 7. Confidence and judge notes",
        f"Confidence: {payload.get('confidence')}",
        payload.get("judge_notes") or "",
        payload.get("research_note") or "",
        "",
    ]
    return "\n".join(lines).replace("—", "...")
