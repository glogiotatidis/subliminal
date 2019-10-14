# -*- coding: utf-8 -*-
import io
import logging
import re
from zipfile import ZipFile

from babelfish import Language
from guessit import guessit
from requests import Session

from . import ParserBeautifulSoup, Provider
from ..cache import EPISODE_EXPIRATION_TIME, region
from ..score import get_equivalent_release_groups
from ..subtitle import Subtitle, fix_line_ending
from ..utils import sanitize, sanitize_release_group
from ..video import Episode, Movie

logger = logging.getLogger(__name__)


class GreekSubsSubtitle(Subtitle):
    provider_name = 'greeksubs'

    def __init__(self, language, subtitle_id, title, downloads):
        super(GreekSubsSubtitle, self).__init__(
            language,
            page_link='http://www.greek-subtitles.com/get_greek_subtitles.php?id={id}'.format(id=subtitle_id)
        )
        self.subtitle_id = subtitle_id
        self.title = title
        self.downloads = downloads

    @property
    def id(self):
        return str(self.subtitle_id)

    def get_matches(self, video):
        matches = set()
        guess = guessit(self.title)

        if video.season and guess.get('season') == video.season:
            matches.add('season')

        if video.episode and guess.get('episode') == video.episode:
            matches.add('episode')

        if video.series and sanitize(guess.get('title')) == sanitize(video.series):
            matches.add('series')

        if video.title and sanitize(guess.get('title')) == sanitize(video.title):
            matches.add('title')

        # release_group
        if (video.release_group and guess.get('release_group') and
                any(r in sanitize_release_group(guess.get('release_group'))
                    for r in get_equivalent_release_groups(sanitize_release_group(video.release_group)))):
            matches.add('release_group')

        return matches


class GreekSubsProvider(Provider):
    languages = {Language('eng'), Language('ell')}
    video_types = (Episode,Movie)

    def initialize(self):
        self.session = Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (X11; Linux x86_64; rv:70.0) Gecko/20100101 Firefox/70.0'

    def terminate(self):
        self.session.close()

    @region.cache_on_arguments(expiration_time=EPISODE_EXPIRATION_TIME)
    def query(self, series, season, episode):
        response = self.session.get(
            'http://www.greek-subtitles.com/search.php',
            params={'name': '{series} S{season:02d}E{episode:02d}'.format(series=series, season=int(season), episode=int(episode))}
        )
        response.raise_for_status()

        soup = ParserBeautifulSoup(response.content, ['html.parser'])
        subtitles = []
        results = soup.select('td.result_top_k')[:-4]
        for i in range(0, len(results) / 4, 4):
            if 'el.gif' in repr(results[i]):
                language = Language('ell')
            elif 'en.gif' in repr(results[i]):
                language = Language('eng')
            subtitle_id = re.search('http://www.greeksubtitles.info/get_greek_subtitles.php\?id=(?P<id>\d+)', repr(results[0])).groupdict()['id']
            title = results[i].text.strip()
            downloads = int(results[i + 3].text.strip())
            subtitle = GreekSubsSubtitle(language, subtitle_id, title, downloads)
            logger.debug('Found subtitle %s', subtitle)
            subtitles.append(subtitle)

        return subtitles

    def list_subtitles(self, video, languages):
        return [s for s in self.query(video.series, video.season, video.episode) if s.language in languages]

    def download_subtitle(self, subtitle):
        # download as a zip
        logger.info('Downloading subtitle %r', subtitle)
        response = self.session.get('http://www.greeksubtitles.info/getp.php?id={}'.format(subtitle.subtitle_id))
        response.raise_for_status()

        with ZipFile(io.BytesIO(response.content)) as zf:
            for filename in zf.namelist():
                if filename.endswith('.srt'):
                    subtitle.content = fix_line_ending(zf.read(filename))
                    break
