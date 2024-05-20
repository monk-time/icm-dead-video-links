#!/usr/bin/env python

"""
A tool to find dead video links in comments on icheckmovies.com.

Links that don't return 200 HTTP status are also checked
via a video host API (e.g. YouTube Data API v3)
for a more precise unavailability reason.

Requires Python 3.6+ with requests and bs4 libraries and a Google API key.
"""

import argparse
import csv
import itertools
import logging
import re
import sys
import urllib.parse
from collections.abc import Collection, Generator, Iterable
from copy import copy
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

PATH_LOG = 'find_dead.log'
PATH_OUT = 'result.md'
PATH_CHECKED_USERS = 'checked_users.txt'
URL_USER_COMMENTS = 'https://www.icheckmovies.com/profiles/comments/'
URL_CHARTS = 'https://www.icheckmovies.com/charts/profiles/'
URL_USERS_BY_CHECKS = 'https://www.icheckmovies.com/profiles/?sort=checks'

try:
    script_path = Path(__file__).resolve().parent
except NameError:
    script_path = Path()


# ----- Logging setup -----


class CustomFormatter(logging.Formatter):
    def format(self, record):
        # the same LogRecord instance is sent to all handlers
        record = copy(record)
        record.msg = record.msg.strip()
        return super().format(record).strip()


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler(script_path / PATH_LOG, encoding='utf-8')
file_handler.setFormatter(
    CustomFormatter(fmt='{asctime} {levelname:8} {message}', style='{')
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
for lib in ['requests', 'urllib3']:
    logging.getLogger(lib).setLevel(logging.WARNING)

# ----- Main -----

try:
    from video_host_utils import VIDEO_HOSTS
except FileNotFoundError as e:
    logging.exception('Google API key is missing.')
    print(*e.args)
    sys.exit(1)


def number_of_pages(user: str) -> int:
    """Get the total number of comment pages of an ICM user."""
    r = requests.get(URL_USER_COMMENTS, {'user': user})
    if r.status_code != requests.codes.ok:
        logging.error(
            f"Error while fetching the first page of {user}'s comments: "
            f'HTTP error {r.status_code}'
        )
        return 0
    if '/login/' in r.url:
        logging.error(f"User {user} doesn't exist.")
        return 0
    soup = BeautifulSoup(r.text, 'html.parser')
    paginator = soup.select('.pages li a')
    if paginator:
        return int(paginator[-1].get_text())
    if len(soup.select('.comment')) == 0:
        return 0
    return 1


def parse_comment(comment: Tag):
    """Extract a movie url and all video ids from an ICM comment."""
    movie = comment.select_one('.link a')
    if movie:
        movie = movie['href']
    text = comment.select_one('.span-18 > span')
    text = text.get_text() if text else ''
    # TODO(monk-time): fix the line above for comments with no text, e.g.:
    # "<span><iframe allowfullscreen="" frameborder="0" height="310"
    # width="508" src="http://www.youtube.com/embed/0qFS5IEctis?wmode=opaque"
    # title="YouTube video player"></iframe></span>"
    for host in VIDEO_HOSTS:
        ids = VIDEO_HOSTS[host].extract(text)
        if ids:
            for vid in ids:
                yield movie, host, vid


def comments_in_profile_page(*, user: str, page: int) -> list[Tag]:
    """Get comments of an ICM user from one page of their profile."""
    r = requests.get(URL_USER_COMMENTS, {'user': user, 'page': page})
    logging.info(f"Checking {user}'s page #{page}")
    if r.status_code != requests.codes.ok:
        logging.error(f'Page #{page}: HTTP error {r.status_code}')
        return []
    soup = BeautifulSoup(r.text, 'html.parser')

    def exclude_login_warning(tag):
        return not tag.find_all(class_='highlightBlock', recursive=False)

    return soup.find_all(exclude_login_warning, class_='comment')


def comments_in_profile(
    *, user: str, from_: int = 1, to: int
) -> Generator[Tag, None, None]:
    """Get all comments of an ICM user.

    Comments may be limited to a subrange (inclusive) of their pages.
    """
    for page in range(from_, to + 1):
        yield from comments_in_profile_page(user=user, page=page)


def dead_in_comments(comments: Iterable[Tag]):
    """Find all dead video links in the given comment elements.

    Supports comments that have several links.
    """
    comments_with_video = itertools.chain.from_iterable(
        map(parse_comment, comments)
    )
    for movie, host, vid in comments_with_video:
        status = VIDEO_HOSTS[host].get_status(vid)
        if status == 'ok':
            logging.debug(f'[{host}] {vid} on {movie}: OK')
            continue
        logging.warning(f'[{host}] {vid} on {movie}: {status}')
        if status == 'not found':
            status = None
        yield movie, host, vid, status


def write_dead_in_profile(*, user: str, from_: int = 1, to: int = 0):
    """Output all dead video links made by an ICM user to a .md file.

    Fetch all comment pages unless a subrange (inclusive) is provided.
    """
    logging.info(f'\nChecking {user}...')
    to = to or number_of_pages(user)
    if to > 0:
        logging.info(f'Got {to} pages of comments')
    comments = comments_in_profile(user=user, from_=from_, to=to)
    dead_links = list(dead_in_comments(comments))
    if not dead_links:
        return
    with (script_path / PATH_OUT).open(mode='a', encoding='utf-8') as f:
        f.write(
            f'## [{user}]({URL_USER_COMMENTS}'
            f'?user={urllib.parse.quote_plus(user)}) '
            f'({len(dead_links)})\n'
        )
        for movie, host, vid, status in dead_links:
            status_text = f'**({status})** ' if status else ''
            f.write(
                f'- [{host}:{vid}]({VIDEO_HOSTS[host].url.format(vid)}) '
                f'{status_text}on '
                f'[{movie}](https://www.icheckmovies.com{movie}comments/)\n'
            )


def top_users(
    *, from_: int = 1, to: int = 1, by_all_checks: bool = False
) -> Generator[str, None, None]:
    """Get all top-ranking users from profile charts or by all checks."""
    logging.info(
        f'Fetching {to - from_ + 1} pages of users from ICM '
        f'(starting from #{from_})...'
    )
    for page in range(from_, to + 1):
        url = URL_USERS_BY_CHECKS if by_all_checks else URL_CHARTS
        r = requests.get(url, {'page': page})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        for t in soup.select('.listItemProfile h2 a'):
            yield t.get_text(strip=True)


def filter_by_blacklist(users: Iterable[str]):
    """Exclude users listed in a blacklist file."""
    with (script_path / PATH_CHECKED_USERS).open(encoding='utf-8') as f:
        checked_users = [s.strip() for s in f if s.strip()]
    yield from (u for u in users if u not in checked_users)


def write_dead_by_users(
    users: Collection[str], *, ignore_blacklist: bool = False
):
    """Output all dead video links made by the given ICM users to a .md file.

    Can use a blacklist file to avoid re-checking users.
    """
    logging.info(f'Got {len(users)} unchecked users')
    if not ignore_blacklist:
        users = list(filter_by_blacklist(users))
        logging.info(
            f'Got {len(users)} unchecked users after applying blacklist '
            f'({PATH_CHECKED_USERS})'
        )
    with (script_path / PATH_CHECKED_USERS).open(
        mode='a',
        buffering=1,
        encoding='utf-8',
    ) as f:
        for user in users:
            write_dead_in_profile(user=user)
            if not ignore_blacklist:
                f.write(user + '\n')


def sort_output_file(filename=PATH_OUT):
    """Sort users in the output file by the number of their dead links desc."""
    with (script_path / filename).open(encoding='utf-8') as f:
        blocks = ['##' + s for s in f.read().split('##') if s]
    blocks_with_lens = [
        (b, int(re.search(r' \((\d+)\)\n', b).group(1))) for b in blocks
    ]
    blocks_with_lens.sort(key=lambda t: (-t[1], t[0]))
    with (script_path / filename).open(mode='w', encoding='utf-8') as f:
        f.writelines(b[0] for b in blocks_with_lens)

    num_dead = sum(n for _, n in blocks_with_lens)
    logging.info(f'{num_dead} dead links in {PATH_OUT}')


def convert_output_file_to_csv(filename=PATH_OUT):
    """Convert the output file to a .CSV format."""
    with (script_path / filename).open(encoding='utf-8') as f:
        blocks = ['##' + s for s in f.read().split('##') if s]

    re_header = re.compile(
        r'^## \[(?P<author>.+?)]\((?P<author_url>.+?)\) \((?P<count>\d+)\)'
    )
    re_row = re.compile(
        r"""
        ^-\s\[(?P<host>\w+):.+?]
        \((?P<video_url>.+?)\)
        (?:\s\*\*\((?P<blocked>blocked\severywhere)\)\*\*)?\s
        on.+\((?P<comment_url>.+)\)$
    """,
        re.VERBOSE,
    )

    full_rows = []
    for block in blocks:
        [first_line, *lines] = block.strip().split('\n')
        author = re_header.match(first_line).groupdict()
        rows = [re_row.match(line).groupdict() for line in lines]

        assert len(rows) == int(author['count'])
        del author['count']
        full_rows.extend({**author, **row} for row in rows)

    csv_path = script_path / Path(filename).with_suffix('.csv')
    with csv_path.open(mode='w', newline='', encoding='utf-8') as f:
        fieldnames = ['author', 'comment_url', 'host', 'video_url', 'blocked']
        writer = csv.DictWriter(f, fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in full_rows:
            writer.writerow(row)

    logging.info(
        f'Exported {len(full_rows)} dead links from {PATH_OUT} as .CSV'
    )


if __name__ == '__main__':
    # noinspection PyTypeChecker
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_argument_group()
    group.add_argument(
        'username', help='find all dead video links by this user', nargs='?'
    )
    group.add_argument(
        '-s',
        '--sort',
        help=f'sort users in {PATH_OUT} by dead links count',
        action='store_true',
    )
    group.add_argument(
        '-c',
        '--convert',
        help=f'convert {PATH_OUT} to .csv',
        action='store_true',
    )
    subgroup = parser.add_argument_group('search users by charts')
    subgroup.add_argument(
        '-t',
        '--top',
        help='check users on the first N pages of profile charts',
        metavar='PAGES',
        type=int,
    )
    subgroup.add_argument(
        '-f',
        '--from',
        dest='minpage',
        help='start from the page #NUM of profile charts',
        metavar='NUM',
        type=int,
    )
    subgroup.add_argument(
        '-i',
        '--ignore-blacklist',
        help=f"don't skip checked users (see {PATH_CHECKED_USERS})",
        action='store_true',
    )
    subgroup.add_argument(
        '-a',
        '--allchecks',
        help='use charts by all checks instead of only official ones',
        action='store_true',
    )
    if len(sys.argv) == 1:  # no arguments given
        parser.print_help()
        parser.exit()
    args = parser.parse_args()
    try:
        if args.username:
            write_dead_in_profile(user=args.username)
        elif args.top:
            minpage = args.minpage or 1
            users_ = list(
                top_users(
                    from_=minpage, to=args.top, by_all_checks=args.allchecks
                )
            )
            write_dead_by_users(users_, ignore_blacklist=args.ignore_blacklist)
        elif args.sort:
            sort_output_file()
        elif args.convert:
            convert_output_file_to_csv()
        else:
            print('No username given.')
            parser.print_usage()
    except KeyboardInterrupt:
        logging.info('Execution stopped by the user.')
        parser.exit()

# TODO(monk-time): turn comment links into beta links
# TODO(monk-time): login first
