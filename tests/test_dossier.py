from mobydick.dossier import render_dossier


def test_render_dossier_order_and_no_emdash():
    md = render_dossier(
        {
            "company": "Harbor Capital",
            "decision_maker": {"full_name": "Chris Whale", "title": "Partner", "linkedin_url": ""},
            "office_ship_to": "10 Pine Street, New York, NY 10005",
            "footprint": {
                "company_pages": 2,
                "youtube_talks": 1,
                "talks_with_transcript": 1,
                "podcast_episodes": 1,
                "cut_bait": False,
            },
            "personal_signals": {
                "hometown_or_from": "Boise",
                "why_got_into_pe": "Family machine shop",
                "beliefs_or_causes": "",
                "quirky_personal_fact": "Fly fishing",
                "best_emotional_hook": "Machine shop kid",
                "sources": ["https://example.com/talk"],
            },
            "gift_ideas": [
                {
                    "gift": "Hometown craft box",
                    "why": "They said they are from Boise.",
                    "buy_link": "https://www.goldbelly.com",
                    "approx_price_usd": "90",
                    "risks": "Skip alcohol.",
                    "receipt_url": "https://example.com/talk",
                    "receipt_note": "They said it on the talk.",
                }
            ],
            "confidence": "medium",
            "judge_notes": "Enough signal.",
            "research_note": "Public sources only.",
        }
    )
    assert md.index("## 1. Company") < md.index("## 2. Decision-maker")
    assert md.index("## 3. Office ship-to") < md.index("## 6. Gift ideas")
    assert "—" not in md
    assert "Chris Whale" in md
