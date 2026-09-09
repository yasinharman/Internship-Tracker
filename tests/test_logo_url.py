"""
The one piece of parsing between a card's <img> and the column the board
renders. Everything here was measured against live pages on 09.09.2026; the
counts are in docs/sites/.
"""

import pytest

from scraper.api_spider import logo_url


@pytest.mark.parametrize("raw,expected", [
    # kariyer.net's listing card, the shape that already works.
    (
        "https://img-kariyer.mncdn.com/mnresize/150/150/UploadFiles/x.png",
        "https://img-kariyer.mncdn.com/mnresize/150/150/UploadFiles/x.png",
    ),
    # techcareer's records point at a CDN that has no working certificate,
    # so an absolute http url is kept as it is rather than upgraded.
    (
        "http://cdn1.kariyer.net/mnresize/112/112/UploadFiles/y.JPG",
        "http://cdn1.kariyer.net/mnresize/112/112/UploadFiles/y.JPG",
    ),
])
def test_an_absolute_url_survives_untouched(raw, expected):
    assert logo_url(raw) == expected


def test_protocol_relative_is_pinned_to_https():
    # 2 of 40 kariyer.net cards arrive this way, and the host answers https.
    assert logo_url("//img-kariyer.mncdn.com/UploadFiles/Clients/z.JPG") == (
        "https://img-kariyer.mncdn.com/UploadFiles/Clients/z.JPG"
    )


def test_the_lazy_load_placeholder_is_not_a_logo():
    # 25 of 40 cards on kariyer.net's first listing page carry this: a 1x1
    # transparent SVG in src, with the company name still in alt. Stored, it
    # would paint an invisible image instead of falling back to the monogram.
    placeholder = (
        "data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%221%22%20"
        "height%3D%221%22%3E%3C%2Fsvg%3E"
    )
    assert logo_url(placeholder) is None


@pytest.mark.parametrize("raw", [None, "", "   ", "N/A", 0, 12, True, b"x"])
def test_nothing_becomes_nothing(raw):
    # "N/A" especially: it is truthy, so it would reach the column and render
    # as <img src="N/A">, which the browser resolves against the board's own
    # origin. It would also make every coverage count report 100%.
    assert logo_url(raw) is None


def test_a_relative_path_needs_a_base_or_it_is_dropped():
    assert logo_url("/UploadFiles/a.png") is None
    assert logo_url("/UploadFiles/a.png", base="https://www.kariyer.net/x") == (
        "https://www.kariyer.net/UploadFiles/a.png"
    )


def test_newlines_and_padding_are_stripped():
    # The DOM loaders hand over text nodes; clean_up_n does this downstream
    # too, but the value is inspected here before it ever reaches a loader.
    assert logo_url("\n  https://cdn.example/x.png  \n") == "https://cdn.example/x.png"
