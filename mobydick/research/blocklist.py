"""People-search and data-broker hosts.

Facts on these sites are often a different person who shares the name.
Blocked in search results, page fetches, and fact extraction.
"""

from __future__ import annotations

from mobydick.research.web import host_key

# Maintained denylist. Match the registrable host and any subdomain.
PEOPLE_SEARCH_HOSTS = frozenset(
    {
        "truepeoplesearch.com",
        "information.com",
        "idcrawl.com",
        "whitepages.com",
        "spokeo.com",
        "beenverified.com",
        "radaris.com",
        "fastpeoplesearch.com",
        "peoplefinders.com",
        "peoplefinder.com",
        "mylife.com",
        "intelius.com",
        "thatsthem.com",
        "peekyou.com",
        "ussearch.com",
        "zabasearch.com",
        "publicrecords.com",
        "clustrmaps.com",
        "nuwber.com",
        "cocofinder.com",
        "anywho.com",
        "addresses.com",
        "familytreenow.com",
        "cyberbackgroundchecks.com",
        "smartbackgroundchecks.com",
        "advancedbackgroundchecks.com",
        "yellowpages.com",
        "411.com",
        "peoplelooker.com",
        "instantcheckmate.com",
        "truthfinder.com",
        "checkpeople.com",
        "voterrecords.com",
        "fastbackgroundcheck.com",
        "pipl.com",
        "socialcatfish.com",
    }
)


def is_people_search(url: str) -> bool:
    """True when the URL is a people-search or data-broker page."""
    host = host_key(url)
    if not host:
        return False
    return any(host == blocked or host.endswith("." + blocked) for blocked in PEOPLE_SEARCH_HOSTS)
