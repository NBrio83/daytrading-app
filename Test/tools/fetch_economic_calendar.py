import os
import json
import pytz
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

_TZ = pytz.FixedOffset(120)  # GMT+02:00
_CACHE = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.tmp', 'economic_calendar.json')
_URL = 'https://se.investing.com/economic-calendar/Service/getCalendarFilteredData'


def fetch_calendar():
    """Scrape se.investing.com for 2- and 3-star events the next 7 days (times in GMT+02:00)."""
    now = datetime.now(_TZ)
    date_from = now.strftime('%Y-%m-%d')
    date_to = (now + timedelta(days=7)).strftime('%Y-%m-%d')

    sess = requests.Session()
    sess.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'sv-SE,sv;q=0.9,en;q=0.8',
    })

    # Acquire session cookies before hitting the AJAX endpoint
    sess.get('https://se.investing.com/economic-calendar/', timeout=25)

    ajax_headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://se.investing.com/economic-calendar/',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Origin': 'https://se.investing.com',
    }

    # importance[]=2 → medium (2 stars), importance[]=3 → high (3 stars)
    # timeZone=8 → UTC; we convert to GMT+2 via data-event-datetime
    body = (
        'importance%5B%5D=2&importance%5B%5D=3'
        '&timeZone=8'
        '&timeFilter=timeRemain'
        '&currentTab=custom'
        '&limit_from=0'
        f'&dateFrom={date_from}&dateTo={date_to}'
    )

    resp = sess.post(_URL, headers=ajax_headers, data=body, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    events = _parse(payload.get('data', ''))
    cache = {'fetched_at': now.isoformat(), 'events': events}

    os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
    with open(_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    return cache


def load_cached():
    try:
        with open(_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'fetched_at': None, 'events': []}


def _parse(html):
    soup = BeautifulSoup(html, 'html.parser')
    events = []
    current_date = ''

    for row in soup.find_all('tr'):
        classes = row.get('class', [])

        # Date separator rows (no class, contain a <td class="theDay">)
        if 'js-event-item' not in classes:
            td = row.find('td', class_='theDay')
            if td:
                current_date = td.get_text(strip=True)
            continue

        # Convert UTC event datetime → GMT+02:00
        dt_attr = row.get('data-event-datetime', '')
        display_time = ''
        display_date = current_date

        if dt_attr:
            try:
                # Format from investing.com: "2026/05/25 01:00:00" (UTC)
                dt_utc = datetime.strptime(dt_attr, '%Y/%m/%d %H:%M:%S')
                dt_utc = pytz.utc.localize(dt_utc)
                dt_local = dt_utc.astimezone(_TZ)
                display_time = dt_local.strftime('%H:%M')
                display_date = dt_local.strftime('%Y-%m-%d')
            except ValueError:
                td_time = row.find('td', class_='js-time')
                display_time = td_time.get_text(strip=True) if td_time else ''

        # Currency / country
        flag_td = row.find('td', class_='flagCur')
        currency, country = '', ''
        if flag_td:
            span = flag_td.find('span')
            country = span.get('title', '') if span else ''
            currency = flag_td.get_text(strip=True)

        # Importance: grayFullBullishIcon = filled star, grayEmptyBullishIcon = empty star
        # 2 stars → 2 grayFullBullishIcon + 1 grayEmptyBullishIcon
        # 3 stars → 3 grayFullBullishIcon + 0 grayEmptyBullishIcon
        sent_td = row.find('td', class_='sentiment')
        importance = 0
        if sent_td:
            importance = len(sent_td.find_all('i', class_='grayFullBullishIcon'))

        if importance < 2:
            continue

        # Event name
        ev_td = row.find('td', class_='event')
        if not ev_td:
            continue
        link = ev_td.find('a')
        event_name = link.get_text(strip=True) if link else ev_td.get_text(strip=True)
        if not event_name:
            continue

        def _cell(cls):
            td = row.find('td', class_=cls)
            return td.get_text(strip=True) if td else ''

        events.append({
            'date': display_date,
            'time': display_time,
            'country': country,
            'currency': currency,
            'event': event_name,
            'importance': importance,
            'actual': _cell('act'),
            'forecast': _cell('fore'),
            'previous': _cell('prev'),
        })

    return events


if __name__ == '__main__':
    import pprint
    pprint.pprint(fetch_calendar())
