import re
from pathlib import Path

import requests

PATH_KEY = 'youtube_data_api.key'
if Path(PATH_KEY).exists():
    YT_API_KEY = Path(PATH_KEY).read_text().strip()
else:
    raise FileNotFoundError(f'Create a file "{PATH_KEY}" in the script directory\n'
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


def extract_yt_ids(s: str):
    """Find all video ids from somewhat valid YT urls in a text string using regex."""
    return [m.group(1) for m in RE_YT_ID.finditer(s)]


def is_valid_yt_video(ytid: str):
    """Check if a given YT video id is valid by sending a HEAD request."""
    r = requests.head(f'https://www.youtube.com/watch?v={ytid}', allow_redirects=True)
    return r.status_code == requests.codes.ok


def yt_video_status(ytid: str) -> str:
    """Get a youtube video status via Youtube Data API v3."""
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
