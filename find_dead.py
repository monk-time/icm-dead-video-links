#!/usr/bin/env python3

"""A tool to find dead youtube links in comments on icheckmovies.com.

Links that don't return 200 HTTP status are also checked
via YouTube Data API v3 for a more precise unavailability reason.

Requires Python 3.6+ with requests and bs4 libraries and a Google API key."""

import argparse
import logging
import operator
import re
import sys
import urllib.parse
from copy import copy
from typing import Iterable, List, Generator, Sequence

import requests
from bs4 import BeautifulSoup, Tag

PATH_LOG = 'find_dead.log'
PATH_OUT = 'result.md'
PATH_CHECKED_USERS = 'checked_users.txt'
URL_USER_COMMENTS = 'https://www.icheckmovies.com/profiles/comments/'
URL_CHARTS = 'https://www.icheckmovies.com/charts/profiles/'
URL_USERS_BY_CHECKS = 'https://www.icheckmovies.com/profiles/?sort=checks'


# --- logging setup ---

class CustomFormatter(logging.Formatter):
    def format(self, record):
        record = copy(record)  # the same LogRecord instance is sent to all handlers
        record.msg = record.msg.strip()
        return super().format(record).strip()


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(PATH_LOG, encoding='utf-8')
file_handler.setFormatter(CustomFormatter(fmt='{asctime} {levelname:8} {message}', style='{'))
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
for lib in ['requests', 'urllib3']:
    logging.getLogger(lib).setLevel(logging.WARNING)

# --- /logging setup ---

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
            if reason == 'ok':
                logging.warning(f'{ytid} on {movie}: NOT 200 OK, but video is available')
                continue
            logging.warning(f'{ytid} on {movie}: {reason}')
            if reason == 'not found':
                reason = None
            yield movie, ytid, reason


def write_dead_in_profile(*, user: str, from_: int = 1, to: int = 0):
    """Find all dead youtube links made by an ICM user and output them to a markdown file.
    Fetches all comment pages unless a subrange (inclusive) is provided."""
    logging.info(f'\nChecking {user}...')
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


def top_users(*, from_: int = 1, to: int = 1, by_all_checks: bool = False) -> Generator[str, None, None]:
    """Get all top ranking users from the first N pages of profile charts or charts by all checks."""
    for page in range(from_, to + 1):
        url = URL_USERS_BY_CHECKS if by_all_checks else URL_CHARTS
        r = requests.get(url, {'page': page})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        for t in soup.select('.listItemProfile h2 a'):
            yield t.get_text(strip=True)


def filter_by_blacklist(users: Iterable[str]):
    """Exclude users listed in a blacklist file."""
    with open(PATH_CHECKED_USERS, encoding='utf-8') as f:
        checked_users = [s.strip() for s in f if s.strip()]
    yield from (u for u in users if u not in checked_users)


def write_dead_by_users(users: Sequence[str], ignore_blacklist: bool = False):
    """Find all dead youtube links made by the given ICM users and output them to a markdown file.
    Can use a blacklist file to avoid re-checking users."""
    # TODO: change the type hint from Sequence to Collection (PyCharm bug PY-24605)
    logging.info(f'Got {len(users)} unchecked users')
    if not ignore_blacklist:
        users = list(filter_by_blacklist(users))
        logging.info(f'Got {len(users)} unchecked users after applying blacklist ({PATH_CHECKED_USERS})')
    with open(PATH_CHECKED_USERS, mode='a', buffering=1, encoding='utf-8') as f:
        for user in users:
            write_dead_in_profile(user=user)
            if not ignore_blacklist:
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_argument_group()
    group.add_argument('username', help='find all dead youtube links by this user', nargs='?')
    subgroup = parser.add_argument_group('by charts')
    subgroup.add_argument('-t', '--top', help='check users on the first N pages of profile charts',
                          metavar='PAGES', type=int)
    subgroup.add_argument('-i', '--ignore-blacklist', help=f"don't skip checked users (see {PATH_CHECKED_USERS})",
                          action='store_true')
    subgroup.add_argument('-a', '--allchecks', help='use charts by all checks instead of only official ones',
                          action='store_true')
    if len(sys.argv) == 1:  # no arguments given
        parser.print_help()
        parser.exit()
    args = parser.parse_args()
    try:
        if args.username:
            write_dead_in_profile(user=args.username)
        elif args.top:
            users_ = list(top_users(to=args.top, by_all_checks=args.allchecks))
            write_dead_by_users(users_, ignore_blacklist=args.ignore_blacklist)
        else:
            print('No username given.')
            parser.print_usage()
    except KeyboardInterrupt:
        logging.info('Execution stopped by the user.')
        parser.exit()
