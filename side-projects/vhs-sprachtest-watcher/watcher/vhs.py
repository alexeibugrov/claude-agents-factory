"""Scrape the Berlin VHS course search by replaying its ASP.NET WebForms postbacks."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

import requests
from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

BASE_URL = "https://www.vhsit.berlin.de/VHSKURSE/BusinessPages/"
SEARCH_URL = BASE_URL + "CourseSearch.aspx"
KEYWORD_SPRACHTEST = "2018"
TITLE_MARKER = "einbürgerung"
MAX_PAGES = 20
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class Course:
    number: str
    district: str
    title: str
    begin: str
    places: str
    booking: str
    url: str

    @property
    def is_free(self) -> bool:
        return self.places.lower() != "belegt" and self.places != ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ScrapeError(RuntimeError):
    pass


def _form_fields(soup: BeautifulSoup) -> dict[str, str]:
    # The page also carries berlin.de's site-search form; the WebForms one holds __VIEWSTATE.
    viewstate = soup.find("input", attrs={"name": "__VIEWSTATE"})
    if viewstate is None:
        raise ScrapeError("no __VIEWSTATE on page — site layout changed?")
    form = viewstate.find_parent("form")
    if not isinstance(form, Tag):
        raise ScrapeError("__VIEWSTATE not inside a form — site layout changed?")
    # Serialise like a browser: hidden/text values, ticked checkboxes (e.g. Bezirk "alle"), and each
    # select's chosen option. Buttons are left out — only the clicked one goes in via `extra`.
    fields: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name:
            continue
        kind = str(el.get("type", "text")).lower()
        if el.name == "select":
            option = el.find("option", selected=True) or el.find("option")
            if isinstance(option, Tag):
                fields[str(name)] = str(option.get("value", option.get_text()))
        elif el.name == "textarea":
            fields[str(name)] = el.get_text()
        elif kind in ("checkbox", "radio"):
            if el.has_attr("checked"):
                fields[str(name)] = str(el.get("value", "on"))
        elif kind not in ("submit", "image", "button", "reset", "file"):
            fields[str(name)] = str(el.get("value", ""))
    return fields


def _cell(row: Tag, cls: str) -> Tag | None:
    cell = row.find("td", class_=cls)
    return cell if isinstance(cell, Tag) else None


def _text(cell: Tag | None) -> str:
    return " ".join(cell.get_text(" ").split()) if cell else ""


def parse_courses(html: str) -> list[Course]:
    soup = BeautifulSoup(html, "html.parser")
    courses = []
    for row in soup.select("tr.DataGridItem, tr.DataGridAlternatingItem"):
        title_cell = _cell(row, "DataGridItemCourseTitle")
        link = title_cell.find("a") if title_cell else None
        href = str(link["href"]) if isinstance(link, Tag) and link.get("href") else ""
        courses.append(
            Course(
                number=_text(_cell(row, "DataGridItemCourseNumber")),
                district=_text(_cell(row, "DataGridItemDistrict")),
                title=_text(title_cell),
                begin=_text(_cell(row, "DataGridItemCourseBegin")),
                places=_text(_cell(row, "DataGridItemPlaces")),
                booking=_text(_cell(row, "DataGridItemBooking")),
                url=BASE_URL + href if href else "",
            )
        )
    return [c for c in courses if c.number]


def _next_page_button(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("input", attrs={"type": "image"}):
        src = str(img.get("src", ""))
        if src.endswith("arrow_right.gif") and not img.has_attr("disabled"):
            return str(img["name"])
    return None


class VhsClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self.timeout = timeout

    def _post(self, url: str, html: str, extra: dict[str, str]) -> requests.Response:
        data = _form_fields(BeautifulSoup(html, "html.parser")) | extra
        resp = self.session.post(url, data=data, headers={"Referer": url}, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def fetch_all(self) -> list[Course]:
        resp = self.session.get(SEARCH_URL, timeout=self.timeout)
        resp.raise_for_status()
        resp = self._post(resp.url, resp.text, {"ctl00$Content$lbtnTab2": "Erweitert"})
        resp = self._post(
            resp.url,
            resp.text,
            {
                "ctl00$Content$KeywordsListAdvanced1$cmbKeyword": KEYWORD_SPRACHTEST,
                "ctl00$Content$KeywordsListAdvanced1$btnAdd": "Hinzufügen",
            },
        )
        resp = self._post(resp.url, resp.text, {"ctl00$Content$btnSearch": "Suchen"})
        if "CourseList.aspx" not in resp.url:
            raise ScrapeError(f"search did not reach the course list (landed on {resp.url})")

        courses = parse_courses(resp.text)
        for _ in range(MAX_PAGES):
            button = _next_page_button(resp.text)
            if button is None:
                break
            resp = self._post(resp.url, resp.text, {f"{button}.x": "5", f"{button}.y": "5"})
            courses.extend(parse_courses(resp.text))

        log.info("fetched %d courses for keyword Sprachtest", len(courses))
        return courses


def einbuergerung_only(courses: list[Course]) -> list[Course]:
    seen: dict[str, Course] = {}
    for c in courses:
        if TITLE_MARKER in c.title.lower():
            seen[c.number] = c
    return list(seen.values())
