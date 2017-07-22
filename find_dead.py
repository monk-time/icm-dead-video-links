#!/usr/bin/env python3

"""A tool to find dead youtube links in comments on icheckmovies.com.

Links that don't return 200 HTTP status are also checked
via YouTube Data API v3 for a more precise unavailability reason.

Requires Python 3.6+ with requests and bs4 libraries and a Google API key."""

import logging
import operator
import re
import sys
import urllib.parse
from typing import Iterable, List, Generator

import requests
from bs4 import BeautifulSoup, Tag

PATH_LOG = 'find_dead.log'
PATH_OUT = 'result.md'
PATH_USERS = 'checked_users.txt'
URL_USER_COMMENTS = 'https://www.icheckmovies.com/profiles/comments/'
URL_CHARTS = 'https://www.icheckmovies.com/charts/profiles/'

logging.basicConfig(filename=PATH_LOG, level=logging.DEBUG,
                    format='{asctime} {levelname:8} {message}', style='{')
logging.getLogger('requests').setLevel(logging.WARNING)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter('{message}', style='{'))
logging.getLogger().addHandler(handler)

try:
    from youtube_utils import extract_yt_ids, is_valid_yt_video, yt_video_status
except FileNotFoundError as e:
    logging.error('Google API key is missing.')
    print(*e.args)
    sys.exit(1)


def number_of_pages(user: str) -> int:
    """Get the total number of comment pages of an ICM user."""
    r = requests.get(URL_USER_COMMENTS, {'user': user})
    if r.status_code != requests.codes.ok:
        logging.error(f"Error while fetching the first page of {user}'s comments: HTTP error {r.status_code}")
        return 0
    if '/login/' in r.url:
        logging.error(f"User {user} doesn't exist.")
        return 0
    soup = BeautifulSoup(r.text, 'html.parser')
    paginator = soup.select('.pages li a')
    return int(paginator[-1].get_text()) if paginator else 1


def parse_comment(comment: Tag):
    """Extract a movie url and all youtube video ids from an ICM comment."""
    movie = comment.select_one('.link a')
    if movie:
        movie = movie['href']
    text = comment.select_one('.span-18 > span')
    text = text.get_text() if text else ''
    return movie, extract_yt_ids(text)


def comments_in_profile_page(*, user: str, page: int) -> List[Tag]:
    """Get comments of an ICM user from one page of their profile."""
    r = requests.get(URL_USER_COMMENTS, {'user': user, 'page': page})
    logging.info(f"Checking {user}'s page #{page} ({r.url})")
    if r.status_code != requests.codes.ok:
        logging.error(f'Page #{page}: HTTP error {r.status_code}')
        return []
    soup = BeautifulSoup(r.text, 'html.parser')

    def exclude_login_warning(tag):
        return not tag.find_all(class_='highlightBlock', recursive=False)

    return soup.find_all(exclude_login_warning, class_='comment')


def comments_in_profile(*, user: str, from_: int = 1, to: int):
    """Get all comments of an ICM user, optionally limited to a subrange (inclusive) of their pages."""
    for page in range(from_, to + 1):
        yield from comments_in_profile_page(user=user, page=page)


def dead_in_comments(comments: Iterable[Tag]):
    """Find all dead youtube links in the given comment elements.
    Supports comments that have several links."""
    comments_with_yt = ((movie, ytid) for movie, ytids in map(parse_comment, comments) if ytids
                        for ytid in ytids)
    for movie, ytid in comments_with_yt:
        if is_valid_yt_video(ytid):
            logging.debug(f'{ytid} on {movie}: 200 OK')
        else:
            reason = yt_video_status(ytid)
            logging.warning(f'{ytid} on {movie}: {reason}')
            if reason == 'not found':
                reason = None
            yield movie, ytid, reason


def write_dead_in_profile(*, user: str, from_: int = 1, to: int = 0):
    """Find all dead youtube links made by an ICM user and output them to a markdown file.
    Fetches all comment pages unless a subrange (inclusive) is provided."""
    to = to or number_of_pages(user)
    logging.info(f'Got {to} pages of comments')
    comments = comments_in_profile(user=user, from_=from_, to=to)
    dead_links = list(dead_in_comments(comments))
    if not dead_links:
        return
    with open(PATH_OUT, mode='a', encoding='utf-8') as f:
        f.write(f'## [{user}]({URL_USER_COMMENTS}?user={urllib.parse.quote_plus(user)}) ({len(dead_links)})\n')
        for movie, ytid, reason in dead_links:
            reason_text = f'**({reason})** ' if reason else ''
            f.write(f'- [{ytid}](https://www.youtube.com/watch?v={ytid}) {reason_text}on '
                    f'[{movie}](https://www.icheckmovies.com{movie}comments/)\n')


def top_users(*, from_: int = 1, to: int) -> Generator[str, None, None]:
    """Get all top ranking users from the first N pages of profile charts."""
    for page in range(from_, to + 1):
        r = requests.get(URL_CHARTS, {'page': page})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        for t in soup.select('.listItemProfile h2 a'):
            yield t.get_text(strip=True)


def write_dead_in_top_users(*, pages: int = 1, use_blacklist: bool = True):
    """Find all dead youtube links made by ICM users in the first N pages of profile charts
    and output them to a markdown file. Uses a blacklist file to avoid re-checking users."""
    users_to_check = list(top_users(to=pages))
    logging.info(f'Got {len(users_to_check)} unchecked users')
    if use_blacklist:
        with open(PATH_USERS) as f:
            checked_users = [s.strip() for s in f if s.strip()]
        users_to_check = [u for u in users_to_check if u not in checked_users]
        logging.info(f'Got {len(users_to_check)} unchecked users after applying blacklist ({PATH_USERS})')
    with open(PATH_USERS, mode='a', buffering=1, encoding='utf-8') as f:
        for user in users_to_check:
            logging.info(f'Checking {user}...')
            write_dead_in_profile(user=user)
            if use_blacklist:
                f.write(user + '\n')


def sort_output_file(filename=PATH_OUT):
    """Modify the output file so that users are sorted by the number of their dead links descending."""
    with open(filename) as f:
        blocks = ['##' + s for s in f.read().split('##') if s]
    blocks_with_lens = [(b, int(re.search(r' \((\d+)\)\n', b).group(1))) for b in blocks]
    blocks_with_lens.sort(key=operator.itemgetter(1), reverse=True)
    with open(filename, mode='w', encoding='utf-8') as f:
        f.writelines(b[0] for b in blocks_with_lens)


if __name__ == '__main__':
    write_dead_in_profile(user='bdcortright')
    # write_dead_in_top_users(5)
    # TODO: console args?
