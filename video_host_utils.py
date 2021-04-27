import re
from functools import partial
from pathlib import Path
from typing import Callable, Pattern

import requests

YT_KEY_FILENAME = 'youtube_data_api.key'
yt_key_path: Path = Path(__file__).resolve().parent / YT_KEY_FILENAME

if yt_key_path.exists():
    YT_API_KEY = yt_key_path.read_text().strip()
else:
    raise FileNotFoundError(f'Create a file "{YT_KEY_FILENAME}" in the script directory\n'
                            f'and put your Google API key inside.\n'
                            'For more info: https://support.google.com/googleapi/answer/6158862')


def extract_video_ids(regex: Pattern, s: str):
    """Find all video ids from video urls in a text string using regex."""
    return [m.group(1) for m in regex.finditer(s)]


PROXIES = {'http': 'proxy-nossl.antizapret.prostovpn.org:29976',
           'https': 'proxy-nossl.antizapret.prostovpn.org:29976'}


def is_alive_video(url: str, vid: str, use_proxy: bool = False):
    """Check if a given video id is available by sending a HEAD request."""
    r = requests.head(url.format(vid), allow_redirects=True, proxies=PROXIES if use_proxy else None)
    return r.status_code == requests.codes.ok


def yt_video_reason(ytid: str) -> str:
    """Get a reson for youtube video unavailability via Youtube Data API v3."""
    r = requests.get(
        'https://www.googleapis.com/youtube/v3/videos',
        {'id': ytid, 'key': YT_API_KEY, 'part': 'status,contentDetails',
         'fields': 'items(status,contentDetails/regionRestriction)'})
    r.raise_for_status()
    yt_response = r.json()
    if not yt_response['items']:
        return 'not found'
    video_info = yt_response['items'][0]
    status = video_info['status']
    if status['privacyStatus'] == 'private':
        return 'private'  # also can be: public, unlisted
    if status['uploadStatus'] != 'processed':
        # also can be: deleted, failed (to upload), rejected (by YT), uploaded (and private?)
        return 'removed'

    if 'contentDetails' not in video_info:
        return 'ok'
    # The video is available but shows a warning about inappropriate content.
    # Example: https://www.youtube.com/watch?v=sVm7Cqm9Z5c
    if 'regionRestriction' not in video_info['contentDetails']:
        return 'ok'

    region = video_info['contentDetails']['regionRestriction']

    if 'allowed' in region:
        n_allowed = len(region['allowed'])
        if n_allowed == 0:
            return 'blocked everywhere'
        elif n_allowed <= 5:
            return f"allowed only in {','.join(sorted(region['allowed']))}"
        else:
            return f"allowed only in {n_allowed} countries"

    if 'blocked' in region:
        n_blocked = len(region['blocked'])
        if n_blocked == 249:  # all officially assigned ISO 3166-1 alpha-2 codes
            return 'blocked everywhere'
        elif n_blocked <= 5:
            return f"blocked in {','.join(region['blocked'])}"
        else:
            return f"blocked in {n_blocked} countries"

    raise RuntimeError(f'Unexpected Youtube API response for {ytid}', yt_response)


class VideoHostToolset:
    def __init__(self, regex: Pattern, url: str,
                 api_url: str = None, use_proxy: bool = False,
                 get_reason: Callable[[str], str] = None):
        self.url = url
        self.extractor = partial(extract_video_ids, regex)
        self.validator = partial(is_alive_video, api_url or url, use_proxy=use_proxy)
        self.get_reason = get_reason


RE_YT_ID = re.compile(r"""
    (?:youtu\.be/|
       youtube\.com/
       (?:(?:vi?|(?:user/)?\w+#p/(?:\w+/)?\w+/\d+|
             e|embed)/|
          (?:[\w?=]+)?[?&]vi?=)
    )
    ([-_a-zA-Z0-9]{11,12})
    """, re.VERBOSE)

RE_VIMEO_ID = re.compile(r'vimeo\.com/(\d+)')
RE_DM_ID = re.compile(r'dailymotion\.com/video/([^"\s]+)')
RE_GV_ID = re.compile(r'video\.google\.com/videoplay\?.*?docid=([-0-9]+)')

URL_YT = 'https://www.youtube.com/watch?v={}'
URL_VIMEO = 'https://vimeo.com/{}'
URL_DM = 'https://www.dailymotion.com/video/{}'
URL_GV = 'http://video.google.com/videoplay?docid={}'

VIDEO_HOSTS = {
    'youtube': VideoHostToolset(RE_YT_ID, URL_YT, get_reason=yt_video_reason),
    'vimeo': VideoHostToolset(RE_VIMEO_ID, URL_VIMEO),
    'dailymotion': VideoHostToolset(RE_DM_ID, URL_DM, use_proxy=True),
    'googlevideo': VideoHostToolset(RE_GV_ID, URL_GV)
}

if __name__ == '__main__':
    # TODO: fix youtube (now it returns 200 for dead links)
    print(VIDEO_HOSTS['youtube'].validator('N9lpD_lWIUo'))  # Video unavailable (account deleted)
    print(VIDEO_HOSTS['youtube'].validator('sVm7Cqm9Z5c'))  # Video unavailable
    print(VIDEO_HOSTS['youtube'].get_reason('sVm7Cqm9Z5c'))  # Video unavailable
    # print(VIDEO_HOSTS['youtube'].validator('SVEfr7Tfm-g'))
    # print(VIDEO_HOSTS['youtube'].validator('OkuxYgBNv9c'))
    # print(VIDEO_HOSTS['dailymotion'].validator('x2bm1t9'))
