from src.extractors.text_heuristics import find_email, find_skills_section, find_projects_section, find_location, find_links

RESUME_TEXT = """Jane Doe
jane.doe @example.com 555-0142
Skills
Programming: Java, C, Python
Cloud: AWS, Docker
Certificates
Some Certificate Issued 2024
Projects
PromptLedger Present
AI Behavior Versioning Platform
Built a full-stack tool that versions AI prompts like Git, runs automated
regression tests on every change, and detects drift in real time.
placeOps 28/12/2025 - 28/12/2025
Full stack project
Built a role-based platform for campus drive management using React.
Languages
English
"""


def test_find_email_tolerates_space_before_at():
    assert find_email(RESUME_TEXT) == "jane.doe@example.com"


def test_find_skills_section_stops_at_next_heading():
    skills = find_skills_section(RESUME_TEXT)
    assert "Programming" in skills
    assert "Java" in skills
    assert "AWS" in skills
    # must not leak into the Certificates section that follows
    assert not any("Certificate" in s for s in skills)
    assert not any("2024" in s for s in skills)


def test_find_projects_section_splits_on_date_or_present_lines():
    projects = find_projects_section(RESUME_TEXT)
    names = [p["name"] for p in projects]
    assert "PromptLedger" in names
    assert "placeOps" in names

    prompt_ledger = next(p for p in projects if p["name"] == "PromptLedger")
    assert "versions AI prompts" in prompt_ledger["summary"]


def test_find_projects_section_missing_heading_returns_empty():
    assert find_projects_section("Just some unrelated text with no sections.") == []


# Icon-only contact header: email/phone/github-icon/linkedin-icon on one
# line (icon glyphs render as bare platform-name words, no URLs attached),
# location/portfolio-icon on the next. This is the layout that triggered
# the bug — "Github"/"LinkedIn" leftover text getting mistaken for a city.
ICON_HEADER_RESUME = """Jane Doe
jane.doe@example.com 555-0142 Github LinkedIn
Coimbatore, TamilNadu Portfolio
Skills
Python, SQL
"""

# Plain-text header with literal inline values: a personal domain sits on
# the same line as email/phone (not a city), and linkedin.com/github.com
# URLs sit on the next line.
INLINE_LINKS_RESUME = """Jane Doe
jane.doe@example.com · 555-0142 · janedoe.tech
linkedin.com/in/janedoe · github.com/janedoe
Skills
Python, SQL
"""


def test_find_location_icon_header_ignores_platform_names():
    assert find_location(ICON_HEADER_RESUME) == "Coimbatore, TamilNadu"


def test_find_location_icon_header_links_not_misattributed():
    links = find_links(ICON_HEADER_RESUME)
    # the icon glyphs rendered as bare words with no URL attached, so there's
    # genuinely nothing to extract here -- the bug was "Github"/"LinkedIn"
    # leaking into location, not that links should magically appear.
    assert links["linkedin"] is None
    assert links["github"] is None


def test_find_location_inline_header_ignores_domain_and_platform_text():
    location = find_location(INLINE_LINKS_RESUME)
    assert location is None or "tech" not in location.lower()
    assert location != "Linkedin Github"


def test_find_location_inline_header_links_correctly_captured():
    links = find_links(INLINE_LINKS_RESUME)
    assert links["linkedin"] == "https://linkedin.com/in/janedoe"
    assert links["github"] == "https://github.com/janedoe"


def test_find_location_rejects_bare_platform_name_on_contact_line():
    text = "Jane Doe\njane.doe@example.com 555-0142 Github\n"
    assert find_location(text) is None


def test_find_location_does_not_misread_skills_line_as_city_region():
    # Regression: a short résumé's "Skills: JavaScript, React, ..." line
    # falling within the header window was misread as a "City, Region" pair
    # ("JavaScript, React") since both are capitalized words joined by a
    # comma -- the same shape as a real location. A real location line has
    # exactly one comma; a skills list has several, and is excluded.
    text = (
        "Jane Doe\n"
        "jane.doe@example.com | (415) 555-0142\n"
        "\n"
        "Skills: JavaScript, React, Python, AWS, Docker\n"
    )
    assert find_location(text) is None
