from country_catalog import (
    CONTINENT_COUNTRIES, COUNTRY_NAMES, COUNTRY_SET, country_choices, pad_to_three,
)


def test_catalog_contains_195_un_states_and_is_unique():
    assert len(COUNTRY_NAMES) == 195
    assert len(COUNTRY_SET) == 195
    assert "Palestine" in COUNTRY_SET
    assert "Vatican City" in COUNTRY_SET


def test_country_choices_preserve_placeholder():
    choices = country_choices("Select a country")
    assert choices[0] == ("", "Select a country")
    assert len(choices) == 196


def test_continent_filter_contains_every_country_once():
    grouped = [country for countries in CONTINENT_COUNTRIES.values() for country in countries]
    assert len(grouped) == 195
    assert set(grouped) == COUNTRY_SET
    assert len(grouped) == len(set(grouped))


def test_home_exposes_complete_country_catalog(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '"Afghanistan"' in html
    assert 'Choose continent' in html
    assert '"Zimbabwe"' in html


def test_country_route_rejects_unknown_country(client):
    response = client.get("/country?country=Atlantis")
    assert response.status_code == 404


def test_country_route_accepts_new_catalog_country(client):
    response = client.get("/country?country=Canada")
    assert response.status_code == 200
    assert "Explore Canada" in response.get_data(as_text=True)


def test_sourced_sections_do_not_invent_placeholder_cards():
    items = [{"name": "Verified place"}]
    result = pad_to_three(items, "Canada", "top_hotels")
    assert len(result) == 1
    assert result[0]["name"] == "Verified place"
