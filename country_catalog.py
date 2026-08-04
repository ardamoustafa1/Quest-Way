"""Verified country catalogue and sourced travel-content lookup.

The catalogue follows the 193 UN member states plus the two UN observer states.
For countries without hand-curated entries in ``travel_data.py``, content is
retrieved from Wikimedia's public MediaWiki API and cached in memory.
"""

from functools import lru_cache
import re

import requests
from bs4 import BeautifulSoup


COUNTRY_NAMES = (
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola",
    "Antigua and Barbuda", "Argentina", "Armenia", "Australia", "Austria",
    "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus",
    "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada",
    "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros",
    "Costa Rica", "Côte d’Ivoire", "Croatia", "Cuba", "Cyprus", "Czechia",
    "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica",
    "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea",
    "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji", "Finland", "France",
    "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada",
    "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras",
    "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland",
    "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya",
    "Kiribati", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho",
    "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar",
    "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands",
    "Mauritania", "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco",
    "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger",
    "Nigeria", "North Korea", "North Macedonia", "Norway", "Oman", "Pakistan",
    "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Republic of the Congo",
    "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis", "Saint Lucia",
    "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles",
    "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka",
    "Sudan", "Suriname", "Sweden", "Switzerland", "Syria", "Tajikistan",
    "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga",
    "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu",
    "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City",
    "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
)

COUNTRY_SET = frozenset(COUNTRY_NAMES)

CONTINENT_COUNTRIES = {
    "Africa": (
        "Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
        "Cabo Verde", "Cameroon", "Central African Republic", "Chad", "Comoros",
        "Côte d’Ivoire", "Democratic Republic of the Congo", "Djibouti", "Egypt",
        "Equatorial Guinea", "Eritrea", "Eswatini", "Ethiopia", "Gabon", "Gambia",
        "Ghana", "Guinea", "Guinea-Bissau", "Kenya", "Lesotho", "Liberia", "Libya",
        "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco",
        "Mozambique", "Namibia", "Niger", "Nigeria", "Republic of the Congo",
        "Rwanda", "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
        "Somalia", "South Africa", "South Sudan", "Sudan", "Tanzania", "Togo",
        "Tunisia", "Uganda", "Zambia", "Zimbabwe",
    ),
    "Asia": (
        "Afghanistan", "Armenia", "Azerbaijan", "Bahrain", "Bangladesh", "Bhutan",
        "Brunei", "Cambodia", "China", "Cyprus", "Georgia", "India", "Indonesia",
        "Iran", "Iraq", "Israel", "Japan", "Jordan", "Kazakhstan", "Kuwait",
        "Kyrgyzstan", "Laos", "Lebanon", "Malaysia", "Maldives", "Mongolia",
        "Myanmar", "Nepal", "North Korea", "Oman", "Pakistan", "Palestine",
        "Philippines", "Qatar", "Saudi Arabia", "Singapore", "South Korea",
        "Sri Lanka", "Syria", "Tajikistan", "Thailand", "Timor-Leste", "Turkey",
        "Turkmenistan", "United Arab Emirates", "Uzbekistan", "Vietnam", "Yemen",
    ),
    "Europe": (
        "Albania", "Andorra", "Austria", "Belarus", "Belgium",
        "Bosnia and Herzegovina", "Bulgaria", "Croatia", "Czechia", "Denmark",
        "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Iceland",
        "Ireland", "Italy", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg",
        "Malta", "Moldova", "Monaco", "Montenegro", "Netherlands",
        "North Macedonia", "Norway", "Poland", "Portugal", "Romania", "Russia",
        "San Marino", "Serbia", "Slovakia", "Slovenia", "Spain", "Sweden",
        "Switzerland", "Ukraine", "United Kingdom", "Vatican City",
    ),
    "North America": (
        "Antigua and Barbuda", "Bahamas", "Barbados", "Belize", "Canada",
        "Costa Rica", "Cuba", "Dominica", "Dominican Republic", "El Salvador",
        "Grenada", "Guatemala", "Haiti", "Honduras", "Jamaica", "Mexico",
        "Nicaragua", "Panama", "Saint Kitts and Nevis", "Saint Lucia",
        "Saint Vincent and the Grenadines", "Trinidad and Tobago", "United States",
    ),
    "South America": (
        "Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador", "Guyana",
        "Paraguay", "Peru", "Suriname", "Uruguay", "Venezuela",
    ),
    "Oceania": (
        "Australia", "Fiji", "Kiribati", "Marshall Islands", "Micronesia", "Nauru",
        "New Zealand", "Palau", "Papua New Guinea", "Samoa", "Solomon Islands",
        "Tonga", "Tuvalu", "Vanuatu",
    ),
}

SECTION_SEARCHES = {
    "famous_places": 'intitle:"{country}" tourist attractions landmarks',
    "top_hotels": 'intitle:"{country}" hotel',
    "top_restaurants": 'intitle:"{country}" restaurant',
    "famous_dishes": 'intitle:"{country}" cuisine food dishes',
    "transport": 'intitle:"{country}" transport',
}

SECTION_CATEGORIES = {
    "famous_places": "Tourist attractions in {country}",
    "top_hotels": "Hotels in {country}",
    "top_restaurants": "Restaurants in {country}",
    "transport": "Transport in {country}",
}

SECTION_REQUIRED_TERMS = {
    "top_hotels": ("hotel", "resort", "inn", "hostel", "lodging"),
    "top_restaurants": ("restaurant", "eatery", "café", "cafe", "dining"),
    "transport": (
        "transport", "railway", "railroad", "airport", "airline", "transit",
        "metro", "subway", "bus", "road", "highway", "tram", "ferry",
    ),
}

SECTION_FALLBACK_IMAGES = {
    "famous_places": "photo-1500530855697-b586d89ba3ee",
    "top_hotels": "photo-1566073771259-6a8506099945",
    "top_restaurants": "photo-1517248135467-4c7edcad34c4",
    "famous_dishes": "photo-1504674900247-0877df9cc836",
    "transport": "photo-1544620347-c4fd4a3d5957",
}

WIKIMEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
REQUEST_HEADERS = {
    "User-Agent": "QuestWay/1.0 (travel content lookup; contact via application owner)"
}


def country_choices(empty_label=None):
    choices = [(country, country) for country in COUNTRY_NAMES]
    return ([("", empty_label)] + choices) if empty_label is not None else choices


def _clean_extract(value):
    value = re.sub(r"\s+", " ", value or "").strip()
    if not value:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", value)
    return " ".join(sentences[:2])[:420]


def _request_pages(params):
    response = requests.get(
        WIKIMEDIA_API, params=params, headers=REQUEST_HEADERS, timeout=10
    )
    response.raise_for_status()
    return response.json().get("query", {}).get("pages", [])


@lru_cache(maxsize=256)
def _resolve_wikivoyage_title(country):
    params = {
        "action": "query", "list": "search", "srsearch": country,
        "srnamespace": 0, "srlimit": 5, "format": "json", "formatversion": 2,
    }
    try:
        response = requests.get(
            WIKIVOYAGE_API, params=params, headers=REQUEST_HEADERS, timeout=10
        )
        response.raise_for_status()
        results = response.json().get("query", {}).get("search", [])
    except (requests.RequestException, ValueError):
        return country
    return results[0]["title"] if results else country


def _fetch_wikivoyage_dishes(country):
    """Extract named foods from the country's sourced Wikivoyage Eat section."""
    page_title = _resolve_wikivoyage_title(country)
    try:
        response = requests.get(
            WIKIVOYAGE_API,
            params={
                "action": "parse", "page": page_title, "prop": "sections",
                "format": "json", "formatversion": 2,
            },
            headers=REQUEST_HEADERS, timeout=10,
        )
        response.raise_for_status()
        sections = response.json().get("parse", {}).get("sections", [])
        eat_section = next(
            (section["index"] for section in sections
             if section.get("line", "").strip().lower() == "eat"),
            None,
        )
        if not eat_section:
            return []
        response = requests.get(
            WIKIVOYAGE_API,
            params={
                "action": "parse", "page": page_title, "section": eat_section,
                "prop": "text", "format": "json", "formatversion": 2,
            },
            headers=REQUEST_HEADERS, timeout=10,
        )
        response.raise_for_status()
        html = response.json().get("parse", {}).get("text", "")
    except (requests.RequestException, ValueError):
        return []

    soup = BeautifulSoup(html, "html.parser")
    first_image = soup.select_one("img")
    image_url = ""
    if first_image and first_image.get("src"):
        image_url = first_image["src"]
        if image_url.startswith("//"):
            image_url = f"https:{image_url}"

    results = []
    seen = set()
    for list_item in soup.select("li"):
        name_node = list_item.find(["b", "strong"])
        if not name_node:
            continue
        name = name_node.get_text(" ", strip=True).strip(" —–-")
        description = re.sub(
            rf"^{re.escape(name)}\s*[—–-]?\s*", "",
            list_item.get_text(" ", strip=True),
        ).strip()
        key = name.casefold()
        if (
            not name or len(name) > 80 or key in seen
            or len(description) < 25
            or any(word in key for word in ("restaurant", "hotel", "district"))
        ):
            continue
        seen.add(key)
        results.append({
            "name": name,
            "description": description[:420],
            "image_url": image_url or (
                "https://images.unsplash.com/"
                f"{SECTION_FALLBACK_IMAGES['famous_dishes']}"
                "?auto=format&fit=crop&w=1200&q=80"
            ),
            "source_url": (
                "https://en.wikivoyage.org/wiki/"
                f"{page_title.replace(' ', '_')}#Eat"
            ),
            "source_name": "Wikivoyage",
        })
        if len(results) == 3:
            break
    return results


def _page_to_item(page, fallback):
    title = (page.get("title") or "").strip()
    description = _clean_extract(page.get("extract"))
    source_url = page.get("fullurl")
    if not title or not description or not source_url:
        return None
    return {
        "name": title,
        "description": description,
        "image_url": page.get("thumbnail", {}).get("source") or fallback,
        "source_url": source_url,
        "source_name": "Wikipedia",
    }


def _fetch_verified_dishes(country, common_params, fallback):
    """Find a country-specific cuisine category, then return actual foods."""
    wikivoyage_results = _fetch_wikivoyage_dishes(country)
    if len(wikivoyage_results) == 3:
        return wikivoyage_results
    exact_params = dict(common_params)
    exact_params.pop("generator", None)
    exact_params.update({
        "titles": f"Cuisine of {country}",
        "redirects": 1,
        "prop": "extracts|pageimages|info|categories",
        "cllimit": "max",
    })
    cuisine_category = None
    try:
        exact_pages = _request_pages(exact_params)
        exact_page = exact_pages[0] if exact_pages else {}
        if not exact_page.get("missing"):
            matching_categories = [
                category.get("title", "")
                for category in exact_page.get("categories", [])
                if category.get("title", "").lower().endswith(" cuisine")
            ]
            if matching_categories:
                cuisine_category = matching_categories[0]
    except (requests.RequestException, ValueError):
        pass

    search_params = dict(common_params)
    search_params.update({
        "generator": "search",
        "gsrsearch": f'"{country}" cuisine traditional dishes',
        "gsrnamespace": 0,
        "gsrlimit": 25,
        "prop": "extracts|pageimages|info|categories",
        "cllimit": "max",
    })
    try:
        candidates = _request_pages(search_params)
    except (requests.RequestException, ValueError):
        return wikivoyage_results

    if not cuisine_category:
        country_lower = country.lower()
        for page in candidates:
            searchable = f"{page.get('title', '')} {page.get('extract', '')}".lower()
            page_title = page.get("title", "")
            if country_lower not in searchable or "cuisine" not in page_title.lower():
                continue
            categories = [
                category.get("title", "")
                for category in page.get("categories", [])
                if category.get("title", "").removeprefix("Category:").lower() == page_title.lower()
            ]
            if categories:
                cuisine_category = categories[0]
                break
    if not cuisine_category:
        return wikivoyage_results

    category_params = dict(common_params)
    category_params.update({
        "generator": "search",
        "gsrsearch": f'incategory:"{cuisine_category.removeprefix("Category:")}" dish',
        "gsrnamespace": 0,
        "gsrlimit": 50,
    })
    try:
        pages = _request_pages(category_params)
    except (requests.RequestException, ValueError):
        return wikivoyage_results

    food_terms = (
        " dish", " food", " bread", " soup", " rice", " meat", " beverage",
        " drink", " pastry", " cake", " stew", " sauce", " cheese", " noodle",
        " dessert", " dumpling", " curry", " kebab", " salad",
    )
    excluded_titles = ("cuisine", "list of", "culture", "agriculture", "restaurant")
    results = list(wikivoyage_results)
    seen_names = {item["name"].casefold() for item in results}
    for page in pages:
        item = _page_to_item(page, fallback)
        if not item:
            continue
        title_lower = item["name"].lower()
        description_lower = item["description"].lower()
        if any(term in title_lower for term in excluded_titles):
            continue
        if not any(term in f" {description_lower}" for term in food_terms):
            continue
        if item["name"].casefold() in seen_names:
            continue
        seen_names.add(item["name"].casefold())
        results.append(item)
        if len(results) == 3:
            break
    return results


@lru_cache(maxsize=1024)
def fetch_sourced_section(country, section):
    """Return up to three real, source-linked Wikimedia results."""
    if country not in COUNTRY_SET or section not in SECTION_SEARCHES:
        return []

    common_params = {
        "action": "query",
        "prop": "extracts|pageimages|info",
        "exintro": 1,
        "explaintext": 1,
        "piprop": "thumbnail",
        "pithumbsize": 900,
        "inprop": "url",
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
        "origin": "*",
    }

    fallback = (
        "https://images.unsplash.com/"
        f"{SECTION_FALLBACK_IMAGES[section]}?auto=format&fit=crop&w=1200&q=80"
    )
    if section == "famous_dishes":
        return _fetch_verified_dishes(country, common_params, fallback)

    params = dict(common_params)
    category = SECTION_CATEGORIES.get(section)
    if category:
        params.update({
            "generator": "categorymembers",
            "gcmtitle": f"Category:{category.format(country=country)}",
            "gcmnamespace": 0,
            "gcmlimit": 20,
        })
    else:
        params.update({
            "generator": "search",
            "gsrsearch": SECTION_SEARCHES[section].format(country=country),
            "gsrnamespace": 0,
            "gsrlimit": 20,
        })

    try:
        pages = _request_pages(params)
        if not pages and category:
            params = dict(common_params)
            params.update({
                "generator": "search",
                "gsrsearch": SECTION_SEARCHES[section].format(country=country),
                "gsrnamespace": 0,
                "gsrlimit": 20,
            })
            pages = _request_pages(params)
    except (requests.RequestException, ValueError):
        return []

    results = []
    seen = set()
    for page in pages:
        title = (page.get("title") or "").strip()
        description = _clean_extract(page.get("extract"))
        source_url = page.get("fullurl")
        searchable = f"{title} {description}".lower()
        # Category membership can be broad. Keep only results whose title or
        # introductory description explicitly anchors them to the country.
        if country.lower() not in searchable:
            continue
        required_terms = SECTION_REQUIRED_TERMS.get(section)
        if required_terms and not any(term in searchable for term in required_terms):
            continue
        if section == "top_restaurants" and any(
            term in title.lower() for term in ("operation ", "province", "district", "city")
        ):
            continue
        if not title or not description or not source_url or title.lower() in seen:
            continue
        seen.add(title.lower())
        results.append(_page_to_item(page, fallback))
        if len(results) == 3:
            break
    return results


def pad_to_three(items, country, section):
    """Backward-compatible helper: return only real sourced items, up to three."""
    return list(items[:3])
