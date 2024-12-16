import re
from collections.abc import Callable
from functools import partial
from pathlib import Path

import requests

YT_KEY_FILENAME = 'youtube_data_api.key'
yt_key_path: Path = Path(__file__).resolve().parent / YT_KEY_FILENAME

if yt_key_path.exists():
    YT_API_KEY = yt_key_path.read_text().strip()
else:
    msg = (
        f'Create a file "{YT_KEY_FILENAME}" in the script directory\n'
        f'and put your Google API key inside.\n'
        'For more info: https://support.google.com/googleapi/answer/6158862'
    )
    raise FileNotFoundError(msg)


def extract_video_ids(regex: re.Pattern, s: str):
    """Find all video ids from video urls in a text string using regex."""
    return [m.group(1) for m in regex.finditer(s)]


PROXIES = {
    'http': 'http://proxy-nossl.antizapret.prostovpn.org:29976',
    'https': 'https://proxy-ssl.antizapret.prostovpn.org:3143',
}


def get_video_status(url: str, vid: str, *, use_proxy: bool = False) -> str:
    """Check if a given video id is available by sending a HEAD request."""
    r = requests.head(
        url.format(vid),
        allow_redirects=True,
        proxies=PROXIES if use_proxy else None,
    )
    return 'ok' if r.status_code == requests.codes.ok else 'not found'


def get_yt_video_status(ytid: str) -> str:  # noqa: PLR0911
    """Check if a youtube video is available via Youtube Data API v3.

    Raises:
        RuntimeError: if received an unexpected Youtube API response.
    """
    r = requests.get(
        'https://www.googleapis.com/youtube/v3/videos',
        {
            'id': ytid,
            'key': YT_API_KEY,
            'part': 'status,contentDetails',
            'fields': 'items(status,contentDetails/regionRestriction)',
        },
    )
    r.raise_for_status()
    yt_response = r.json()
    if not yt_response['items']:
        return 'not found'
    video_info = yt_response['items'][0]
    status = video_info['status']
    if status['privacyStatus'] == 'private':
        return 'private'  # also can be: public, unlisted
    if status['uploadStatus'] != 'processed':
        # also can be: deleted, failed (to upload),
        # rejected (by YT), uploaded (and private?)
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
        return 'ok'

    if 'blocked' in region:
        n_blocked = len(region['blocked'])
        # 249 = all officially assigned ISO 3166-1 alpha-2 codes
        if n_blocked == 249:
            return 'blocked everywhere'
        return 'ok'

    msg = f'Unexpected Youtube API response for {ytid}'
    raise RuntimeError(msg, yt_response)


class VideoHostToolset:
    def __init__(
        self,
        *,
        regex: re.Pattern,
        url: str,
        use_proxy: bool = False,
        get_status: Callable[[str], str] | None = None,
    ):
        self.url = url
        self.extract = partial(extract_video_ids, regex)
        self.get_status = (
            partial(get_video_status, url, use_proxy=use_proxy)
            if get_status is None
            else get_status
        )


RE_YT_ID = re.compile(
    r"""
    (?:youtu\.be/|
       youtube\.com/
       (?:(?:vi?|(?:user/)?\w+#p/(?:\w+/)?\w+/\d+|
             e|embed)/|
          (?:[\w?=]+)?[?&]vi?=)
    )
    ([-_a-zA-Z0-9]{11,12})
    """,
    re.VERBOSE,
)

VIDEO_HOSTS = {
    'youtube': VideoHostToolset(
        regex=RE_YT_ID,
        url='https://www.youtube.com/watch?v={}',
        get_status=get_yt_video_status,
    ),
    'vimeo': VideoHostToolset(
        regex=re.compile(r'vimeo\.com/(\d+)'), url='https://vimeo.com/{}'
    ),
    'dailymotion': VideoHostToolset(
        regex=(re.compile(r'dailymotion\.com/video/([^"\s]+)')),
        url='https://www.dailymotion.com/video/{}',
        use_proxy=True,
    ),
    'googlevideo': VideoHostToolset(
        regex=re.compile(r'video\.google\.com/videoplay\?.*?docid=([-0-9]+)'),
        url='http://video.google.com/videoplay?docid={}',
    ),
}

if __name__ == '__main__':
    print(VIDEO_HOSTS['youtube'].get_status('dQw4w9WgXcQ'))  # ok
    print(
        VIDEO_HOSTS['youtube'].get_status('N9lpD_lWIUo')
    )  # unavailable (account deleted)
    print(
        VIDEO_HOSTS['youtube'].get_status('OkuxYgBNv9c')
    )  # unavailable (copyright claim)
    print(
        VIDEO_HOSTS['youtube'].get_status('PZMywkeqpx4')
    )  # unavailable (private)
    print(VIDEO_HOSTS['youtube'].get_status('sVm7Cqm9Z5c'))  # unavailable
    print(VIDEO_HOSTS['youtube'].get_status('SVEfr7Tfm-g'))  # unavailable
    print(VIDEO_HOSTS['dailymotion'].get_status('x2bm1t9'))  # ok
