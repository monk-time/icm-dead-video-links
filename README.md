# icm-dead-video-links
A tool to find dead video links in comments on icheckmovies.com.

Looks for video links in all comments left by a set of users, then queries video host APIs for video status. Currently supports the following video hosts:
- Youtube
- Vimeo
- Dailymotion
- Google Video

### Dependencies
- Python 3
- requests
- BeautifulSoup4

### Usage
```
usage: find_dead.py [-h] [-s] [-c] [-t PAGES] [-f NUM] [-i] [-a] [username]

A tool to find dead video links in comments on icheckmovies.com.

Links that don't return 200 HTTP status are also checked
via a video host API (e.g. YouTube Data API v3)
for a more precise unavailability reason.

Requires Python 3.6+ with requests and bs4 libraries and a Google API key.

options:
  -h, --help            show this help message and exit

  username              find all dead video links by this user
  -s, --sort            sort users in result.md by dead links count
  -c, --convert         convert result.md to .csv

search users by charts:
  -t PAGES, --top PAGES
                        check users on the first N pages of profile charts
  -f NUM, --from NUM    start from the page #NUM of profile charts
  -i, --ignore-blacklist
                        don't skip checked users (see checked_users.txt)
  -a, --allchecks       use charts by all checks instead of only official ones
```

### How to run:
1. Create a virtual environment and install dependencies:
   ```console
   $ python -m venv venv
   $ . venv/Scripts/activate
   $ pip install -r requirements.txt
   ```
3. Create a new file `youtube_data_api.key` in the script directory and put your [Google API key](https://support.google.com/googleapi/answer/6158862) into it.
4. Run the script:
   ```console
   $ python find_dead.py
   ```
