# -*- coding: utf-8 -*-
'''
***********************************************************
*
* @file addon.py
*
* Created on 2026-08-22.
*
* @license GNU General Public License, version 3 (GPL-3.0)
*
********************************************************cm*
'''

import re
import os
import sys
import json
import html
import base64

from urllib.parse import urlencode, unquote, parse_qsl, quote_plus, urlparse, urljoin, parse_qs
from datetime import datetime, timezone

import requests
import xbmc
import xbmcvfs
import xbmcgui
import xbmcplugin
import xbmcaddon


addon_url = sys.argv[0]
addon_handle = int(sys.argv[1])
params = dict(parse_qsl(sys.argv[2][1:]))
addon = xbmcaddon.Addon(id='plugin.video.dlhd')
mode = addon.getSetting('mode')

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
FANART = addon.getAddonInfo('fanart')
ICON = addon.getAddonInfo('icon')

SEED_BASEURL = 'https://dlstreams.st/'

def log(msg):
    logpath = xbmcvfs.translatePath('special://logpath/')
    filename = 'dlhd.log'
    log_file = os.path.join(logpath, filename)
    try:
        if isinstance(msg, str):
            _msg = f'\n    {msg}'
        else:
            _msg = f'\n    {repr(msg)}'
        if not os.path.exists(log_file):
            with open(log_file, 'w', encoding='utf-8'):
                pass
        with open(log_file, 'a', encoding='utf-8') as f:
            line = ('[{} {}]: {}').format(datetime.now().date(), str(datetime.now().time())[:8], _msg)
            f.write(line.rstrip('\r\n') + '\n')
    except (TypeError, Exception) as e:
        try:
            xbmc.log(f'[ DLHD ] Logging Failure: {e}', 2)
        except:
            pass

def normalize_origin(url):
    try:
        u = urlparse(url)
        return f'{u.scheme}://{u.netloc}/'
    except:
        return SEED_BASEURL

def resolve_active_baseurl(seed):
    try:
        s = requests.Session()
        headers = {'User-Agent': UA}
        resp = s.get(seed, headers=headers, timeout=10, allow_redirects=True)
        final = normalize_origin(resp.url if resp.url else seed)
        return final
    except Exception as e:
        log(f'Active base resolve failed, using seed. Error: {e}')
        return normalize_origin(seed)

def get_active_base():
    base = addon.getSetting('active_baseurl')
    if not base:
        base = resolve_active_baseurl(SEED_BASEURL)
        addon.setSetting('active_baseurl', base)
    if not base.endswith('/'):
        base += '/'
    return base

def set_active_base(new_base: str):
    if not new_base.endswith('/'):
        new_base += '/'
    addon.setSetting('active_baseurl', new_base)

def abs_url(path: str) -> str:
    return urljoin(get_active_base(), path.lstrip('/'))

def _sched_headers():
    base = get_active_base()
    return {'User-Agent': UA, 'Referer': base, 'Origin': base}

def get_local_time(utc_time_str):
    try:
        utc_now = datetime.utcnow()
        event_time_utc = datetime.strptime(utc_time_str, '%H:%M')
        event_time_utc = event_time_utc.replace(year=utc_now.year, month=utc_now.month, day=utc_now.day)
        event_time_utc = event_time_utc.replace(tzinfo=timezone.utc)
        local_time = event_time_utc.astimezone()
        time_format_pref = addon.getSetting('time_format')
        if time_format_pref == '1':
            local_time_str = local_time.strftime('%H:%M')
        else:
            local_time_str = local_time.strftime('%I:%M %p').lstrip('0')
        return local_time_str
    except Exception as e:
        log(f"Failed to convert time: {e}")
        return utc_time_str

def build_url(query):
    return addon_url + '?' + urlencode(query)

def addDir(title, dir_url, is_folder=True):
    li = xbmcgui.ListItem(title)
    clean_plot = re.sub(r'<[^>]+>', '', title)
    labels = {'title': title, 'plot': clean_plot, 'mediatype': 'video'}
    kodiversion = getKodiversion()
    if kodiversion < 20:
        li.setInfo("video", labels)
    else:
        infotag = li.getVideoInfoTag()
        infotag.setMediaType(labels.get("mediatype", "video"))
        infotag.setTitle(labels.get("title", "DLHD"))
        infotag.setPlot(labels.get("plot", labels.get("title", "DLHD")))
    li.setArt({'thumb': '', 'poster': '', 'banner': '', 'icon': ICON, 'fanart': FANART})
    li.setProperty("IsPlayable", 'false' if is_folder else 'true')
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=dir_url, listitem=li, isFolder=is_folder)

def closeDir():
    xbmcplugin.endOfDirectory(addon_handle)

def getKodiversion():
    try:
        return int(xbmc.getInfoLabel("System.BuildVersion")[:2])
    except:
        return 18

def Main_Menu():
    menu = [
        ['[B][COLOR red]LIVE SPORTS SCHEDULE[/COLOR][/B]', 'sched'],
        ['[B][COLOR red]LIVE TV CHANNELS[/COLOR][/B]', 'live_tv'],
        ['[B][COLOR red]SEARCH EVENTS SCHEDULE[/COLOR][/B]', 'search'],
        ['[B][COLOR red]SEARCH LIVE TV CHANNELS[/COLOR][/B]', 'search_channels'],
        ['[B][COLOR red]REFRESH CATEGORIES[/COLOR][/B]', 'refresh_sched'],
        ['[B][COLOR red]SET ACTIVE DOMAIN (AUTO)[/COLOR][/B]', 'resolve_base_now'],
    ]
    for m in menu:
        addDir(m[0], build_url({'mode': 'menu', 'serv_type': m[1]}))
    closeDir()

def getCategTrans():
    schedule_url = abs_url('index.php')
    try:
        headers = {'User-Agent': UA, 'Referer': get_active_base()}
        html_text = requests.get(schedule_url, headers=headers, timeout=10).text

        m = re.search(r'<div[^>]+class="filters"[^>]*>(.*?)</div>', html_text, re.IGNORECASE | re.DOTALL)
        if not m:
            log("getCategTrans(): filters block not found")
            return []

        block = m.group(1)
        anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
        if not anchors:
            log("getCategTrans(): no <a> items in filters block")
            return []

        categs = []
        seen = set()

        for href, text_content in anchors:
            name = html.unescape(re.sub(r'\s+', ' ', text_content)).strip()
            if not name or name.lower() == 'all':
                continue
            if name in seen:
                continue
            seen.add(name)
            categs.append((name, '[]'))

        return categs

    except Exception as e:
        xbmcgui.Dialog().ok("Error", f"Error fetching category data: {e}")
        log(f'index parse fail: url={schedule_url} err={e}')
        return []

def Menu_Trans():
    categs = getCategTrans()
    if not categs:
        return
    for categ_name, _events_list in categs:
        addDir(categ_name, build_url({'mode': 'showChannels', 'trType': categ_name}))
    closeDir()

def ShowChannels(categ, channels_list):
    for item in channels_list:
        title = item.get('title')
        addDir(title, build_url({'mode': 'trList', 'trType': categ, 'channels': json.dumps(item.get('channels'))}), True)
    closeDir()

def getTransData(categ):
    try:
        url = abs_url('index.php?cat=' + quote_plus(categ))
        headers = {'User-Agent': UA, 'Referer': get_active_base()}
        html_text = requests.get(url, headers=headers, timeout=10).text

        cut = re.search(r'<h2\s+class="collapsible-header\b', html_text, re.IGNORECASE)
        if cut:
            html_text = html_text[:cut.start()]

        events = re.findall(
            r'<div\s+class="schedule__event">.*?'
            r'<div\s+class="schedule__eventHeader"[^>]*?>\s*'
            r'(?:<[^>]+>)*?'
            r'<span\s+class="schedule__time"[^>]*data-time="([^"]+)"[^>]*>.*?</span>\s*'
            r'<span\s+class="schedule__eventTitle">\s*([^<]+)\s*</span>.*?'
            r'</div>\s*'
            r'<div\s+class="schedule__channels">(.*?)</div>',
            html_text, re.IGNORECASE | re.DOTALL
        )

        trns = []
        for time_str, event_title, channels_block in events:
            event_time_local = get_local_time(time_str.strip())
            title = f'[COLOR gold]{event_time_local}[/COLOR] {html.unescape(event_title.strip())}'

            chans = []
            for href, title_attr, link_text in re.findall(
                r'<a[^>]+href="([^"]+)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
                channels_block, re.IGNORECASE | re.DOTALL
            ):
                try:
                    u = urlparse(href)
                    qs = dict(parse_qsl(u.query))
                    cid = qs.get('id') or ''
                except Exception:
                    cid = ''
                name = html.unescape((title_attr or link_text).strip())
                if cid:
                    chans.append({'channel_name': name, 'channel_id': cid})

            if chans:
                trns.append({'title': title, 'channels': chans})

        return trns

    except Exception as e:
        log(f'getTransData error for categ={categ}: {e}')
        return []

def TransList(categ, channels):
    for channel in channels:
        channel_title = html.unescape(channel.get('channel_name'))
        channel_id = str(channel.get('channel_id', '')).strip()
        if not channel_id:
            continue
        addDir(channel_title, build_url({'mode': 'trLinks', 'trData': json.dumps({'channels': [{'channel_name': channel_title, 'channel_id': channel_id}]})}), False)
    closeDir()

def getSource(trData):
    try:
        data = json.loads(unquote(trData))
        channels_data = data.get('channels')
        if channels_data and isinstance(channels_data, list):
            cid = str(channels_data[0].get('channel_id', '')).strip()
            if not cid:
                return
            if '%7C' in cid or '|' in cid:
                url_stream = abs_url('watchs2watch.php?id=' + cid)
            else:
                url_stream = abs_url('embed/stream-' + cid + '.php')
            xbmcplugin.setContent(addon_handle, 'videos')
            PlayStream(url_stream)
    except Exception as e:
        log(f'getSource failed: {e}')

def list_gen():
    chData = channels()
    for c in chData:
        addDir(c[1], build_url({'mode': 'play', 'url': abs_url(c[0])}), False)
    closeDir()

def channels():
    url = abs_url('24-7-channels.php')
    allow_adult = xbmcaddon.Addon().getSetting('adult_pw') == 'lol'
    headers = {'Referer': get_active_base(), 'User-Agent': UA}

    try:
        resp = requests.post(url, headers=headers, timeout=10).text
    except Exception as e:
        log(f"[DADDYLIVE] channels(): request failed: {e}")
        return []

    card_rx = re.compile(
        r'<a\s+class="card"[^>]*?href="(?P<href>[^"]+)"[^>]*?data-title="(?P<data_title>[^"]*)"[^>]*>'
        r'.*?<div\s+class="card__title">\s*(?P<title>.*?)\s*</div>'
        r'.*?ID:\s*(?P<id>\d+)\s*</div>'
        r'.*?</a>',
        re.IGNORECASE | re.DOTALL
    )

    items = []
    for m in card_rx.finditer(resp):
        href_rel = m.group('href').strip()
        title_dom = html.unescape(m.group('title').strip())
        title_attr = html.unescape(m.group('data_title').strip())
        name = title_dom or title_attr

        is_adult = ('18+' in name) or ('18+' in title_attr) or name.lower().startswith('18+')
        if is_adult and not allow_adult:
            continue

        name = re.sub(r'^\s*\d+(?=[A-Za-z])', '', name).strip()

        items.append([href_rel, name])

    if not items:
        log("[DADDYLIVE] channels(): Site may have changed.")

    return items

def PlayStream(link):
    try:
        base = get_active_base()
        session = requests.Session()

        def _origin(u):
            try:
                p = urlparse(u)
                return f'{p.scheme}://{p.netloc}'
            except:
                return ''

        def _fetch(u, ref=None, note=''):
            headers = {
                'User-Agent': UA,
                'Referer': base,
                'Origin': _origin(base),
            }
            if ref:
                headers['Referer'] = ref
                headers['Origin'] = _origin(ref)
            log(f'[PlayStream] GET {u}  (ref={headers.get("Referer")}) {note}')
            r = session.get(u, headers=headers, timeout=10)
            r.raise_for_status()
            return r.text, r.url

        def _format_link(url):
            if "watch.php?id=" in url:
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                cid = query_params.get('id')[0]
                new_url = abs_url('embed/stream-' + cid + '.php')
                return new_url
            else:
                return url

        formatted_link = _format_link(link)
        html1, url1 = _fetch(formatted_link, ref=base, note='entry')

        try:
            matches = re.compile("iframe src=\"(.*)\" width").findall(html1)
            source_url = matches[0]
            log(f"source_url: {source_url}")
        except Exception as e:
            log(f"Error: {e}")

        try:
            source_resp, srurl = _fetch(source_url, ref=base, note='source response')
            m3u8_redirect_url_encoded = re.search(r'window\.atob\(["\']([A-Za-z0-9+/=]+)["\']\)', source_resp).group(1)
            m3u8_redirect_url = base64.b64decode(m3u8_redirect_url_encoded).decode('utf-8')
            log(f"m3u8_redirect_url: {m3u8_redirect_url}")
        except Exception as e:
            log(f"Error: {e}")

        try:
            m3u8_redirect_resp, m3u8rdurl = _fetch(m3u8_redirect_url, ref=source_url, note='m3u8 index url response')
            for line in m3u8_redirect_resp.split("\n"):
                if line.startswith('#'):
                    if line.startswith('#EXT-X-STREAM-INF'):
                        m3u8_stream_info = line
                elif line != '':
                    m3u8_playlist_url = urljoin(m3u8_redirect_url, line)
        except Exception as e:
            log(f"Error: {e}")

        host_raw = _origin(source_url)
        header_dict = {
            'Referer': f'{host_raw}/',
            'Origin': host_raw,
            'Connection': 'Keep-Alive',
            'User-Agent': UA,
        }

        header_str = '&'.join(f'{k}={quote_plus(v)}' for k, v in header_dict.items())
        m3u8 = f'{m3u8_playlist_url}|{header_str}'
        log(f'[PlayStream] Final HLS = {m3u8}')

        liz = xbmcgui.ListItem('DLHD', path=m3u8)
        liz.setProperty('inputstream', 'inputstream.ffmpegdirect')
        liz.setMimeType('application/x-mpegURL')
        liz.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
        liz.setProperty('inputstream.ffmpegdirect.stream_mode', 'timeshift')
        liz.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')

        xbmcplugin.setResolvedUrl(addon_handle, True, liz)

    except Exception as e:
        import traceback
        log(f"[PlayStream] Exception: {e}\n{traceback.format_exc()}")

def Search_Events():
    keyboard = xbmcgui.Dialog().input("Enter search term", type=xbmcgui.INPUT_ALPHANUM)
    if not keyboard or keyboard.strip() == '':
        return
    term = keyboard.lower().strip()

    try:
        base = get_active_base()
        headers = {'User-Agent': UA, 'Referer': base}
        html_text = requests.get(abs_url('index.php'), headers=headers, timeout=10).text

        events = re.findall(
            r"<div\s+class=\"schedule__event\">.*?"
            r"<div\s+class=\"schedule__eventHeader\"[^>]*?>\s*"
            r"(?:<[^>]+>)*?"
            r"<span\s+class=\"schedule__time\"[^>]*data-time=\"([^\"]+)\"[^>]*>.*?</span>\s*"
            r"<span\s+class=\"schedule__eventTitle\">\s*([^<]+)\s*</span>.*?"
            r"</div>\s*"
            r"<div\s+class=\"schedule__channels\">(.*?)</div>",
            html_text, re.IGNORECASE | re.DOTALL
        )

        rows = {}
        seen = set()
        for time_str, raw_title, channels_block in events:
            title_clean = html.unescape(raw_title.strip())
            if term not in title_clean.lower():
                continue

            local_ts = get_local_time(time_str.strip())
            row_title = f"[COLOR gold]{local_ts}[/COLOR] {title_clean}"

            for href, title_attr, link_text in re.findall(
                r"<a[^>]+href=\"([^\"]+)\"[^>]*title=\"([^\"]*)\"[^>]*>(.*?)</a>",
                channels_block, re.IGNORECASE | re.DOTALL
            ):
                try:
                    u = urlparse(href)
                    qs = dict(parse_qsl(u.query))
                    cid = (qs.get('id') or '').strip()
                except Exception:
                    cid = ''
                if not cid:
                    continue

                sig = (title_clean.lower(), time_str.strip(), cid)
                if sig in seen:
                    continue
                seen.add(sig)

                ch_name = html.unescape((title_attr or link_text or '').strip()) or 'Channel'
                rows.setdefault(row_title, [])
                if all(cid != c['channel_id'] for c in rows[row_title]):
                    rows[row_title].append({'channel_name': ch_name, 'channel_id': cid})

        if not rows:
            xbmcgui.Dialog().ok("Search", "No matching events found.")
            return

        for row_title, chans in rows.items():
            addDir(row_title, build_url({'mode': 'trList', 'trType': 'search', 'channels': json.dumps(chans)}), True)
        closeDir()

    except Exception as e:
        log(f"Search_Events (fast) error: {e}")
        xbmcgui.Dialog().ok("Search", "Search failed. Check log.")

def Search_Channels():
    keyboard = xbmcgui.Dialog().input("Enter channel name", type=xbmcgui.INPUT_ALPHANUM)
    if not keyboard or keyboard.strip() == '':
        return
    term = keyboard.lower().strip()

    try:
        base = get_active_base()
        headers = {'User-Agent': UA, 'Referer': base}
        html_text = requests.get(abs_url('index.php'), headers=headers, timeout=10).text

        channel_blocks = re.findall(
            r"<div\s+class=\"schedule__event\">.*?"
            r"<div\s+class=\"schedule__eventHeader\"[^>]*?>.*?</div>\s*"
            r"<div\s+class=\"schedule__channels\">(.*?)</div>",
            html_text, re.IGNORECASE | re.DOTALL
        )

        results = []
        seen = set()
        for block in channel_blocks:
            for href, title_attr, link_text in re.findall(
                r"<a[^>]+href=\"([^\"]+)\"[^>]*title=\"([^\"]*)\"[^>]*>(.*?)</a>",
                block, re.IGNORECASE | re.DOTALL
            ):
                display = html.unescape((title_attr or link_text or '').strip())
                if term not in display.lower():
                    continue

                try:
                    u = urlparse(href)
                    qs = dict(parse_qsl(u.query))
                    cid = (qs.get('id') or '').strip()
                except Exception:
                    cid = ''
                if not cid:
                    continue

                sig = (display.lower(), cid)
                if sig in seen:
                    continue
                seen.add(sig)

                results.append({'title': display, 'channel_id': cid})

        if not results:
            xbmcgui.Dialog().ok("Search", "No matching channels found.")
            return

        for result in results:
            addDir(result['title'], build_url({
                'mode': 'trLinks',
                'trData': json.dumps({'channels': [{'channel_name': result["title"], 'channel_id': result["channel_id"]}]})
            }), False)
        closeDir()

    except Exception as e:
        log(f"Search_Channels (fast) error: {e}")
        xbmcgui.Dialog().ok("Search", "Search failed. Check log.")

def refresh_active_base():
    new_base = resolve_active_baseurl(SEED_BASEURL)
    set_active_base(new_base)
    xbmcgui.Dialog().ok("DLHD", f"Active domain set to:\n{new_base}")
    xbmc.executebuiltin('Container.Refresh')

kodiversion = getKodiversion()
mode = params.get('mode', None)

if not mode:
    Main_Menu()
else:
    if mode == 'menu':
        servType = params.get('serv_type')
        if servType == 'sched':
            Menu_Trans()
        elif servType == 'live_tv':
            list_gen()
        elif servType == 'search':
            Search_Events()
        elif servType == 'search_channels':
            Search_Channels()
        elif servType == 'refresh_sched':
            xbmc.executebuiltin('Container.Refresh')

    elif mode == 'showChannels':
        transType = params.get('trType')
        channels = getTransData(transType)
        ShowChannels(transType, channels)

    elif mode == 'trList':
        transType = params.get('trType')
        channels = json.loads(params.get('channels'))
        TransList(transType, channels)

    elif mode == 'trLinks':
        trData = params.get('trData')
        getSource(trData)

    elif mode == 'play':
        link = params.get('url')
        PlayStream(link)

    elif mode == 'resolve_base_now':
        refresh_active_base()
