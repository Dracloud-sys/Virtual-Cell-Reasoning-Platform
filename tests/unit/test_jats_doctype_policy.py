"""What the JATS parser accepts, and what it still refuses, now that real bodies carry a DOCTYPE.

Europe PMC serves every open-access JATS body with an external DOCTYPE (`<!DOCTYPE article
PUBLIC "-//NLM//DTD JATS ..." "JATS-archivearticle1-4-mathml3.dtd">`). The parser refused any
DOCTYPE by regex, so every real body failed to parse, and no fixture caught it because none
carried one.

The policy is narrower than "allow DOCTYPE": an external PUBLIC/SYSTEM declaration with **no
internal subset** is accepted and never followed; an internal subset (even `[]`), any entity
declaration, any external entity reference and any entity the document does not define are
refused. Every attack input here is a small synthetic document, and "nothing was fetched" is
measured by instrumenting file and socket access during the parse, not inferred from the
network being unavailable.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import os
import socket
import urllib.request

import pytest

from virtualcell.literature.contracts import ArticleIdentifier
from virtualcell.literature.documents import JatsParseError, parse_jats

ARTICLE = ArticleIdentifier(pmcid="PMC0000001")

#: The shape Europe PMC actually serves: an external PUBLIC DOCTYPE, no internal subset.
REAL_DOCTYPE = (
    '<!DOCTYPE article\n  PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange '
    'DTD with MathML3 v1.4 20241031//EN" "JATS-archivearticle1-4-mathml3.dtd">\n'
)

REAL_SHAPED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    + REAL_DOCTYPE
    + '<article xml:lang="en" article-type="research-article" dtd-version="1.4">\n'
    "<front><article-meta><abstract><p>Abstract with &#177; and &#x3b1; and caf\u00e9.</p>"
    "</abstract>\n"
    '<permissions><license xmlns:xlink="http://www.w3.org/1999/xlink"\n'
    ' xlink:href="https://creativecommons.org/licenses/by/4.0/"/></permissions>\n'
    "</article-meta></front>\n<body>\n"
    '<!-- a comment that mentions <!ENTITY fake "x"> and <!DOCTYPE other> is not a '
    "declaration -->\n"
    '<sec id="sec1"><title>Results</title><p>Collagen rose 2&#8211;3 fold &amp; stayed '
    '&lt; 5 \u2014 "quoted".</p></sec>\n'
    '<sec id="sec2"><title>Discussion</title><p>Processed collagen was in the construct.'
    '<![CDATA[ <!ENTITY q "r"> & "literal" ]]> Media held proforms.</p></sec>\n'
    "</body></article>"
)


# --- accepted ---------------------------------------------------------------------------


def test_a_real_shaped_body_with_an_external_doctype_parses() -> None:
    document = parse_jats(REAL_SHAPED, article=ARTICLE)

    assert [s.title for s in document.sections] == ["Results", "Discussion"]
    assert document.license == "https://creativecommons.org/licenses/by/4.0/"


def test_the_content_hash_is_still_of_the_original_bytes() -> None:
    document = parse_jats(REAL_SHAPED, article=ARTICLE)

    assert document.content_hash == hashlib.sha256(REAL_SHAPED.encode("utf-8")).hexdigest()


def test_character_references_and_unicode_survive_and_nothing_is_dropped() -> None:
    document = parse_jats(REAL_SHAPED, article=ARTICLE)
    results, discussion = (s.text for s in document.sections)

    assert document.abstract == "Abstract with ± and α and café."
    assert results == 'Collagen rose 2–3 fold & stayed < 5 — "quoted".'
    # The CDATA text is kept verbatim, and the text on either side of it is not lost.
    assert discussion.startswith("Processed collagen was in the construct.")
    assert '<!ENTITY q "r"> & "literal"' in discussion
    assert discussion.endswith("Media held proforms.")


def test_a_system_only_external_doctype_parses() -> None:
    xml = '<!DOCTYPE article SYSTEM "JATS.dtd"><article><body><sec><p>x</p></sec></body></article>'

    assert parse_jats(xml, article=ARTICLE).sections[0].text == "x"


def test_a_body_with_no_doctype_still_parses() -> None:
    xml = "<article><body><sec><title>T</title><p>y</p></sec></body></article>"

    assert parse_jats(xml, article=ARTICLE).sections[0].text == "y"


# --- refused ----------------------------------------------------------------------------

REFUSED = {
    "empty internal subset": "<!DOCTYPE article []><article/>",
    "internal subset, general entity": (
        '<!DOCTYPE article [<!ENTITY x "smuggled">]><article><body><sec><p>&x;</p></sec>'
        "</body></article>"
    ),
    "internal subset beside an external id": (
        '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS//EN" "JATS.dtd" [<!ENTITY x "y">]>'
        "<article>&x;</article>"
    ),
    "parameter entity": '<!DOCTYPE article [<!ENTITY % p "x"> %p;]><article/>',
    "entity expansion (small billion laughs)": (
        '<!DOCTYPE lolz [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;"><!ENTITY c "&b;&b;&b;">]>'
        "<lolz>&c;</lolz>"
    ),
    "unparsed entity with a notation": (
        '<!DOCTYPE article [<!NOTATION n SYSTEM "n"><!ENTITY u SYSTEM "u.bin" NDATA n>]><article/>'
    ),
    "undefined entity, no doctype": "<article><p>&secret;</p></article>",
    "undefined entity under an external doctype": (
        '<!DOCTYPE article SYSTEM "JATS.dtd"><article><p>before &secret; after</p></article>'
    ),
    "malformed": "<article><body><sec>unclosed",
}


@pytest.mark.parametrize("xml", list(REFUSED.values()), ids=list(REFUSED))
def test_a_refused_construct_is_a_parse_error_not_a_guess(xml: str) -> None:
    with pytest.raises(JatsParseError):
        parse_jats(xml, article=ARTICLE)


# --- nothing named by the document is read or fetched -----------------------------------


@pytest.fixture
def access_log(monkeypatch):
    """Record every file open and outbound connection attempted during the test body.

    Installed per test with monkeypatch and removed after it. The product code patches
    nothing; this is the measurement.
    """
    log: list[tuple[str, str]] = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def spy_open(file, *args, **kwargs):
        log.append(("open", str(file)))
        return real_open(file, *args, **kwargs)

    def spy_io_open(file, *args, **kwargs):
        log.append(("io.open", str(file)))
        return real_io_open(file, *args, **kwargs)

    def spy_os_open(path, *args, **kwargs):
        log.append(("os.open", str(path)))
        return real_os_open(path, *args, **kwargs)

    def spy_connect(self, address):
        log.append(("connect", str(address)))
        raise OSError("connection attempted during a parse")

    def spy_create_connection(address, *args, **kwargs):
        log.append(("create_connection", str(address)))
        raise OSError("connection attempted during a parse")

    def spy_urlopen(url, *args, **kwargs):
        log.append(("urlopen", str(url)))
        raise OSError("urlopen attempted during a parse")

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_io_open)
    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr(socket.socket, "connect", spy_connect)
    monkeypatch.setattr(socket, "create_connection", spy_create_connection)
    monkeypatch.setattr(urllib.request, "urlopen", spy_urlopen)
    return log


def _sentinel_dtd(tmp_path) -> str:
    """A local DTD defining an entity, so reading it would visibly change the result."""
    path = tmp_path / "sentinel.dtd"
    path.write_text('<!ENTITY secret "SENTINEL-FROM-LOCAL-FILE">', encoding="utf-8")
    return path.as_uri()


def test_an_external_doctype_is_never_followed_to_a_local_file(tmp_path, access_log) -> None:
    uri = _sentinel_dtd(tmp_path)
    access_log.clear()
    xml = f'<!DOCTYPE article SYSTEM "{uri}"><article><p>&secret;</p></article>'

    with pytest.raises(JatsParseError) as caught:
        parse_jats(xml, article=ARTICLE)

    assert access_log == []
    assert "SENTINEL" not in str(caught.value)


def test_an_external_doctype_is_never_followed_over_the_network(access_log) -> None:
    xml = (
        '<!DOCTYPE article PUBLIC "-//X//EN" "http://127.0.0.1:9/evil.dtd">'
        "<article><body><sec><p>plain text</p></sec></body></article>"
    )

    document = parse_jats(xml, article=ARTICLE)

    assert document.sections[0].text == "plain text"
    assert access_log == []


def test_an_external_entity_declaration_is_refused_without_reading_it(tmp_path, access_log) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("SENTINEL-FILE-CONTENT", encoding="utf-8")
    access_log.clear()
    xml = f'<!DOCTYPE a [<!ENTITY x SYSTEM "{target.as_uri()}">]><a>&x;</a>'

    with pytest.raises(JatsParseError):
        parse_jats(xml, article=ARTICLE)

    assert access_log == []


def test_an_xinclude_element_is_inert(tmp_path, access_log) -> None:
    target = tmp_path / "included.xml"
    target.write_text("<p>SENTINEL-INCLUDED</p>", encoding="utf-8")
    access_log.clear()
    xml = (
        REAL_DOCTYPE + '<article xmlns:xi="http://www.w3.org/2001/XInclude"><body><sec>'
        f'<p>kept</p><xi:include href="{target.as_uri()}"/></sec></body></article>'
    )

    document = parse_jats(xml, article=ARTICLE)

    assert "SENTINEL" not in document.sections[0].text
    assert document.sections[0].text == "kept"
    assert access_log == []


def test_the_real_shaped_body_parses_without_touching_file_or_network(access_log) -> None:
    parse_jats(REAL_SHAPED, article=ARTICLE)

    assert access_log == []
