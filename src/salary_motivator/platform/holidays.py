"""Sync Taiwan public holidays from the DGPA open-data calendar.

Source: 行政院人事行政總處, 政府資料開放平臺 dataset 14718
(中華民國政府行政機關辦公日曆表). The dataset page lists one CSV
per year; each row is 西元日期 (YYYYMMDD), 星期, 是否放假
(0 = 上班, 2 = 放假), 備註. A 補班 (make-up workday) is marked in
the 備註 as 補行上班.

Only the standard library is used, and nothing is downloaded until
the user presses the sync button in the settings dialog.
"""

import csv
import datetime as dt
import io
import re
import urllib.parse
import urllib.request

from ..model import is_workday

DATASET_URL = "https://data.gov.tw/dataset/14718"
REQUEST_TIMEOUT = 15


def _find_year_csv(page_text, year):
    """Return the download URL of the year's calendar CSV from the dataset page."""
    roc_year = year - 1911
    wanted = f"{roc_year}年中華民國政府行政機關辦公日曆表.csv"
    page_text = page_text.replace("&amp;", "&")
    pattern = r"https://www\.dgpa\.gov\.tw/FileConversion\?[^\s\"']+"
    for match in re.finditer(pattern, page_text):
        url = match.group(0)
        if ".csv" not in url:
            continue
        name = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(
            "name", [""]
        )[0]
        if urllib.parse.unquote(name) == wanted:
            # Some links carry the file name unencoded; quote it for the request.
            return urllib.parse.quote(url, safe=":/?&=%.-_")
    raise OSError(f"在政府資料開放平臺找不到 {year} 年的辦公日曆表。")


def _parse_calendar(csv_text, year):
    """Return (holidays, makeup_days) as sets of dates for the given year."""
    holidays = set()
    makeup_days = set()
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        raw_date = (row.get("西元日期") or "").strip()
        try:
            day = dt.datetime.strptime(raw_date, "%Y%m%d").date()
        except ValueError:
            continue
        if day.year != year:
            continue
        if (row.get("備註") or "").strip().find("補行上班") >= 0:
            makeup_days.add(day)
        elif (row.get("是否放假") or "").strip() == "2":
            holidays.add(day)
    return holidays, makeup_days


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SalaryMotivator"})
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)


def fetch_holidays(year):
    """Download the year's calendar; return (holidays, makeup_days)."""
    with _open(DATASET_URL) as response:
        page_text = response.read().decode("utf-8", errors="replace")
    csv_url = _find_year_csv(page_text, year)
    with _open(csv_url) as response:
        csv_text = response.read().decode("utf-8-sig", errors="replace")
    return _parse_calendar(csv_text, year)


def sync_holidays(settings, year):
    """Mark the year's holidays/make-up days in settings['overrides'].

    Only days whose holiday status differs from the default rest mode
    get an override, and days the user already marked by hand are left
    alone. Returns (holidays_marked, makeup_days_marked, skipped).
    """
    holidays, makeup_days = fetch_holidays(year)
    overrides = settings["overrides"]
    marked = makeup = skipped = 0
    for day in sorted(holidays):
        if day.isoformat() in overrides:
            skipped += 1
        elif is_workday(day, settings):
            overrides[day.isoformat()] = False
            marked += 1
    for day in sorted(makeup_days):
        if day.isoformat() in overrides:
            skipped += 1
        elif not is_workday(day, settings):
            overrides[day.isoformat()] = True
            makeup += 1
    return marked, makeup, skipped
