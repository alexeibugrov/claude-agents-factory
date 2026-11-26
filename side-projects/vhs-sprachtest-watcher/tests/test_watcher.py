import random
from datetime import datetime
from zoneinfo import ZoneInfo

from watcher import state
from watcher.main import Schedule, format_changes
from watcher.vhs import _next_page_button, einbuergerung_only, parse_courses

TZ = ZoneInfo("Europe/Berlin")


def _row(cls: str, number: str, title: str, places: str, district: str = "Pankow") -> str:
    return f"""
    <tr class="{cls}">
      <td class="DataGridItemBasket"></td><td class="DataGridColumnWishList"></td>
      <td class="DataGridItemDistrict">{district}</td>
      <td class="DataGridItemCourseNumber">{number}</td>
      <td class="DataGridItemCourseTitle"><a href="CourseDetail.aspx?id=1">{title}</a></td>
      <td class="DataGridItemCourseBegin">27.11.2026
        08:00 Uhr</td>
      <td class="DataGridItemPlaces">{places}</td>
      <td class="DataGridItemBooking">Aufnahme in Warteliste möglich</td>
      <td class="DataGridItemCosts">€ 75.00</td>
    </tr>"""


PAGE = f"""<html><body><form id="aspnetForm"><input type="hidden" name="__VIEWSTATE" value="x"/>
<table>
{_row("DataGridItem", "Sp4.003.06H-26", "Sprachtest zur Einbürgerung", "belegt", "Spandau")}
{_row("DataGridAlternatingItem", "TS404.941H", "Sprachtest zur Einbürgerung B1", "3")}
{_row("DataGridItem", "SZ814-101-10d", "Prüfungsvorbereitung telc Deutsch B2", "&gt; 2")}
</table>
<input type="image" name="ctl00$g$ctl01$ctl04" src="../Design/Pictures/grid/arrow_right.gif"/>
</form></body></html>"""


def test_parse_and_filter() -> None:
    courses = parse_courses(PAGE)
    assert [c.number for c in courses] == ["Sp4.003.06H-26", "TS404.941H", "SZ814-101-10d"]
    assert courses[0].begin == "27.11.2026 08:00 Uhr"
    assert courses[0].url.endswith("CourseDetail.aspx?id=1")
    assert not courses[0].is_free and courses[1].is_free
    assert [c.number for c in einbuergerung_only(courses)] == ["Sp4.003.06H-26", "TS404.941H"]


def test_next_page_button() -> None:
    assert _next_page_button(PAGE) == "ctl00$g$ctl01$ctl04"
    disabled = PAGE.replace('arrow_right.gif"', 'arrow_right.gif" disabled="disabled"')
    assert _next_page_button(disabled) is None


def test_diff_new_and_freed() -> None:
    old = einbuergerung_only(parse_courses(PAGE))
    previous = {c.number: c.to_dict() | {"places": "belegt"} for c in old}
    current = einbuergerung_only(parse_courses(PAGE.replace("Sp4.003.06H-26", "NEW-1")))
    changes = state.diff(previous, current)
    assert [c.number for c in changes.new] == ["NEW-1"]
    assert [c.number for c in changes.freed] == ["TS404.941H"]
    assert "NEW-1" in format_changes(changes)


def test_diff_unchanged_is_empty() -> None:
    courses = einbuergerung_only(parse_courses(PAGE))
    assert not state.diff({c.number: c.to_dict() for c in courses}, courses)


def test_schedule_stays_in_window() -> None:
    sched = Schedule(start_hour=7, end_hour=20, min_gap=45, max_gap=75)
    rng = random.Random(1)
    t = datetime(2026, 11, 26, 6, 0, tzinfo=TZ)
    t = sched.next_window_start(t, rng)
    for _ in range(500):
        assert sched.in_window(t), t
        nxt = sched.next_run(t, rng)
        assert nxt > t
        t = nxt


def test_schedule_evening_rolls_to_next_morning() -> None:
    sched = Schedule(start_hour=7, end_hour=20, min_gap=45, max_gap=75)
    nxt = sched.next_run(datetime(2026, 11, 26, 19, 30, tzinfo=TZ), random.Random(2))
    assert nxt.date().day == 27 and nxt.hour == 7


def test_form_fields_serialise_like_a_browser() -> None:
    from bs4 import BeautifulSoup

    from watcher.vhs import _form_fields

    html = """<form id="aspnetForm">
      <input type="hidden" name="__VIEWSTATE" value="vs"/>
      <input type="checkbox" name="d$0" checked="checked"/>
      <input type="checkbox" name="d$1"/>
      <input type="text" name="q" value=""/>
      <select name="kw"><option value="0">Bitte</option><option value="2018">Sprachtest</option></select>
      <select name="ts"><option value="a">A</option><option value="b" selected>B</option></select>
      <input type="submit" name="btn" value="Suchen"/>
      <input type="image" name="img" src="x.gif"/>
    </form>"""
    assert _form_fields(BeautifulSoup(html, "html.parser")) == {
        "__VIEWSTATE": "vs",
        "d$0": "on",
        "q": "",
        "kw": "0",
        "ts": "b",
    }


def test_failure_tracker_alerts_first_reminds_and_recovers() -> None:
    from watcher.main import REMIND_EVERY, FailureTracker

    tracker = FailureTracker()
    assert tracker.succeeded() is None
    sent = [tracker.failed(RuntimeError(f"boom {i}")) for i in range(1, REMIND_EVERY + 1)]
    assert sent[0] is not None and "boom 1" in sent[0]
    assert all(m is None for m in sent[1:-1])
    assert sent[-1] is not None and str(REMIND_EVERY) in sent[-1]
    recovered = tracker.succeeded()
    assert recovered is not None and "wieder OK" in recovered
    assert tracker.succeeded() is None


def test_crash_alert_is_rate_limited(tmp_path) -> None:
    import time

    from watcher.main import CRASH_ALERT_MIN_GAP_S, crash_alert_allowed

    now = time.time()
    assert crash_alert_allowed(tmp_path, now)
    assert not crash_alert_allowed(tmp_path, now + 60)
    assert crash_alert_allowed(tmp_path, now + CRASH_ALERT_MIN_GAP_S + 1)
