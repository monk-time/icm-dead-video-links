import re
from functools import partial
from pathlib import Path
from typing import Pattern, NamedTuple, Callable, List

import requests

YT_KEY_FILENAME = 'youtube_data_api.key'
yt_key_path = Path(__file__).resolve().parent / YT_KEY_FILENAME

if yt_key_path.exists():
    YT_API_KEY = yt_key_path.read_text().strip()
else:
    raise FileNotFoundError(f'Create a file "{YT_KEY_FILENAME}" in the script directory\n'
                            f'and put your Google API key inside.\n'
                            'For more info: https://support.google.com/googleapi/answer/6158862')

RE_YT_ID = re.compile(r"""
    (?:youtu\.be/|
       youtube\.com/
       (?:(?:vi?|(?:user/)?\w+\#p/(?:\w+/)?\w+/\d+|
             e|embed)/|
          (?:[\w?=]+)?[?&]vi?=)
    )
    ([-_a-zA-Z0-9]{11,12})
    """, re.VERBOSE)

RE_VIMEO_ID = re.compile(r'vimeo\.com/(\d+)')


def extract_video_ids(regex: Pattern, s: str):
    """Find all video ids from video urls in a text string using regex."""
    return [m.group(1) for m in regex.finditer(s)]


def is_valid_video(url: str, vid: str):
    """Check if a given video id is valid by sending a HEAD request."""
    r = requests.head(url.format(vid), allow_redirects=True)
    return r.status_code == requests.codes.ok


extract_yt_ids = partial(extract_video_ids, RE_YT_ID)
extract_vimeo_ids = partial(extract_video_ids, RE_VIMEO_ID)
yt_url = 'https://www.youtube.com/watch?v={}'
vimeo_url = 'https://vimeo.com/{}'
is_valid_yt_video = partial(is_valid_video, yt_url)
is_valid_vimeo_video = partial(is_valid_video, vimeo_url)


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


class VideoHostToolset(NamedTuple):
    url: str
    extractor: Callable[[str], List[str]]
    validator: Callable[[str], bool]
    get_reason: Callable[[str], str] = None


VIDEO_HOSTS = {
    'youtube': VideoHostToolset(yt_url, extract_yt_ids, is_valid_yt_video, yt_video_reason),
    'vimeo': VideoHostToolset(vimeo_url, extract_vimeo_ids, is_valid_vimeo_video)
}
