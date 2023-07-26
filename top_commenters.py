from collections import Counter
from typing import Iterable, List, Tuple

import requests
from bs4 import BeautifulSoup

from find_dead import write_dead_by_users


def number_of_pages(movie: str) -> int:
    """Get the total number of comment pages on a movie page."""
    r = requests.get(f'https://www.icheckmovies.com/movies/{movie}/comments/')
    if r.status_code != requests.codes.ok:
        print(f"Error while fetching the first page of comments on {movie}: "
              f"HTTP error {r.status_code}")
        return 0
    soup = BeautifulSoup(r.text, 'html.parser')
    paginator = soup.select('.pages li a')
    return int(paginator[-1].get_text()) if paginator else 1


def all_movies_on_a_list(url: str) -> Iterable[str]:
    r = requests.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    for el in soup.select('.listItemMovie h2 a'):
        yield el['href'].replace('/movies/', '').rstrip('/')


def commenters(movie: str) -> Counter:
    n = number_of_pages(movie)
    c = Counter()
    print(f'Fetching {n} comment pages of "{movie}"')
    for page in range(1, n + 1):
        r = requests.get(f'https://www.icheckmovies.com/movies/{movie}/comments/', {'page': page})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        c.update(el.get_text() for el in soup.select('.comment h3 a'))
    return c


def top_commenters_on_movies_in_a_list(url: str, min_comments: int = 0) -> List[Tuple[str, int]]:
    summary = sum((commenters(m) for m in all_movies_on_a_list(url)), Counter())
    return [(el, cnt) for el, cnt in summary.most_common() if cnt > min_comments]


if __name__ == '__main__':
    url_ = 'https://www.icheckmovies.com/lists/icheckmovies+most+favorite+shorts/mjf314/'
    top_commenters = top_commenters_on_movies_in_a_list(url_)
    print('Top commenters:\n', top_commenters)
    # users_to_check = list(user for user, cnt in top_commenters)
    # write_dead_by_users(users_to_check)
