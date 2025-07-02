# -*- coding: utf-8 -*-
import enum
import io
import logging
import re
import zipfile
import time
from random import randint
from urllib.parse import urlparse, parse_qs, quote

import rarfile
from guessit import guessit
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError

from subliminal.cache import region as cache
from subliminal.exceptions import AuthenticationError, ConfigurationError, DownloadLimitExceeded, ProviderError
from subliminal.providers import ParserBeautifulSoup
from subliminal.subtitle import fix_line_ending
from subliminal.video import Episode, Movie

from subliminal_patch.providers import Provider
from subliminal_patch.providers.mixins import ProviderSubtitleArchiveMixin

from subliminal_patch.subtitle import Subtitle, guess_matches

from subliminal_patch.pitcher import pitchers, load_verification, store_verification

from dogpile.cache.api import NO_VALUE
from subzero.language import Language

from .utils import FIRST_THOUSAND_OR_SO_USER_AGENTS as AGENT_LIST

logger = logging.getLogger(__name__)


class SubtitlesType(enum.Enum):
    EPISODE = enum.auto()
    MOVIE = enum.auto()

class TitulkySubtitle(Subtitle):
    provider_name = 'titulky'

    hash_verifiable = False
    hearing_impaired_verifiable = False

    def __init__(self,
                 sub_id,
                 imdb_id,
                 language,
                 season,
                 episode,
                 release_info,
                 uploader,
                 approved,
                 page_link,
                 download_link,
                 fps,
                 skip_wrong_fps,
                 asked_for_episode=None):
        super().__init__(language, page_link=page_link)

        self.sub_id = sub_id
        self.imdb_id = imdb_id
        self.season = season
        self.episode = episode
        self.releases = [release_info]
        self.release_info = release_info
        self.approved = approved
        self.page_link = page_link
        self.uploader = uploader
        self.download_link = download_link
        self.fps = fps if skip_wrong_fps else None # This attribute should be ignored if skip_wrong_fps is false
        self.skip_wrong_fps = skip_wrong_fps
        self.asked_for_episode = asked_for_episode
        self.matches = None

    @property
    def id(self):
        return self.sub_id

    def get_matches(self, video):
        matches = set()
        media_type = 'movie' if isinstance(video, Movie) else 'episode'

        if self.skip_wrong_fps and video.fps and self.fps and not framerate_equal(video.fps, self.fps):
            logger.debug(f"Titulky.com: Wrong FPS (expected: {video.fps}, got: {self.fps}, lowering score massively)")
            return set()

        if media_type == 'episode':
            # match imdb_id of a series
            if video.series_imdb_id and video.series_imdb_id == self.imdb_id:
                matches |= {'series_imdb_id', 'series', 'year'}

            # match season/episode
            if self.season and self.season == video.season:
                matches.add('season')
            if self.episode and self.episode == video.episode:
                matches.add('episode')

        elif media_type == 'movie':
            # match imdb_id of a movie
            if video.imdb_id and video.imdb_id == self.imdb_id:
                matches |= {'imdb_id', 'title', 'year'}

        matches |= guess_matches(video, guessit(self.release_info, {"type": media_type}))

        self.matches = matches

        return matches


class TitulkyProvider(Provider, ProviderSubtitleArchiveMixin):
    languages = {Language(l) for l in ['ces', 'slk']}
    video_types = (Episode, Movie)
    hash_verifiable = False
    hearing_impaired_verifiable = False

    premium_server_url = 'https://premium.titulky.com'
    normal_server_url = 'https://www.titulky.com'
    premium_login_url = premium_server_url
    normal_login_url = normal_server_url
    premium_logout_url = f"{premium_server_url}?action=logout"
    normal_logout_url = f"{normal_server_url}?action=logout"
    premium_download_url = f"{premium_server_url}/download.php?id="
    normal_download_url = f"{normal_server_url}/idown.php?R=&zip=&histstamp=&toUTF=1&T=1-1652287319136&titulky="
    captcha_img_url = f"{normal_server_url}/captcha/captcha.php"
    captcha_url = f"{normal_server_url}/idown.php"

    timeout = 30
    max_threads = 5

    subtitle_class = TitulkySubtitle

    def __init__(self,
                 username=None,
                 password=None,
                 approved_only=None,
                 skip_wrong_fps=None):
        if not all([username, password]):
            raise ConfigurationError("Username and password must be specified!")
        if type(approved_only) is not bool:
            raise ConfigurationError(f"Approved_only {approved_only} must be a boolean!")
        if type(skip_wrong_fps) is not bool:
            raise ConfigurationError(f"Skip_wrong_fps {skip_wrong_fps} must be a boolean!")

        self.username = username
        self.password = password
        self.approved_only = approved_only
        self.skip_wrong_fps = skip_wrong_fps

        self.premium_session = None
        self.normal_session = None

    def initialize(self):
        self.premium_session = Session()
        self.normal_session = Session()

        # Set headers
        cached_user_agent = cache.get('titulky_user_agent')
        if cached_user_agent == NO_VALUE:
            new_user_agent = AGENT_LIST[randint(0, len(AGENT_LIST) - 1)]
            cache.set('titulky_user_agent', new_user_agent)
            self.premium_session.headers['User-Agent'] = new_user_agent
            self.normal_session.headers['User-Agent'] = new_user_agent
        else:
            self.premium_session.headers['User-Agent'] = cached_user_agent
            self.normal_session.headers['User-Agent'] = cached_user_agent

        self.premium_session.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        self.normal_session.headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        self.premium_session.headers['Accept-Language'] = 'cz,sk,en;q=0.5'
        self.normal_session.headers['Accept-Language'] = 'cz,sk,en;q=0.5'
        self.premium_session.headers['Accept-Encoding'] = 'gzip, deflate'
        self.normal_session.headers['Accept-Encoding'] = 'gzip, deflate'
        self.premium_session.headers['DNT'] = '1'
        self.normal_session.headers['DNT'] = '1'
        self.premium_session.headers['Connection'] = 'keep-alive'
        self.normal_session.headers['Connection'] = 'keep-alive'
        self.premium_session.headers['Upgrade-Insecure-Requests'] = '1'
        self.normal_session.headers['Upgrade-Insecure-Requests'] = '1'
        self.premium_session.headers['Cache-Control'] = 'max-age=0'
        self.normal_session.headers['Cache-Control'] = 'max-age=0'

        self.login()

    def terminate(self):
        self.premium_session.close()
        self.normal_session.close()

    def login(self, bypass_cache=False):
        # Reuse all cookies if found in cache and skip login.
        cached_cookiejar = cache.get('premium_titulky_cookiejar')
        if not bypass_cache and cached_cookiejar != NO_VALUE:
            logger.info("Titulky.com: Reusing cached premium cookies.")
            self.premium_session.cookies.update(cached_cookiejar)
            # return True
        else:
            logger.info("Titulky.com: Logging in to premium server...")

            data = {'LoginName': self.username, 'LoginPassword': self.password}
            res = self.premium_session.post(self.premium_server_url,
                                    data,
                                    allow_redirects=False,
                                    timeout=self.timeout,
                                    headers={'Referer': self.premium_server_url})

            location_qs = parse_qs(urlparse(res.headers['Location']).query)

            # If the response is a redirect and doesnt point to an error message page, then we are logged in
            if not (res.status_code == 302 and location_qs['msg_type'][0] == 'i'):
                raise AuthenticationError("Login to premium server failed")
            else:
                if 'omezené' in location_qs['msg'][0]:
                    raise AuthenticationError("V.I.P. account is required for this provider to work!")
                else:
                    logger.info("Titulky.com: Successfully logged in to premium server, caching cookies for future connections...")
                    cache.set('premium_titulky_cookiejar', self.premium_session.cookies.copy())
                    # return True

        # Reuse all cookies if found in cache and skip login.
        cached_cookiejar = cache.get('normal_titulky_cookiejar')
        if not bypass_cache and cached_cookiejar != NO_VALUE:
            logger.info("Titulky.com: Reusing cached normal cookies.")
            self.normal_session.cookies.update(cached_cookiejar)
            return True

        logger.info("Titulky.com: Logging in to normal server...")

        data = {'Login': self.username, 'Detail2': '', 'prihlasit': 'Přihlásit', 'Detail2': '', 'Password': self.password, 'foreverlog': '1'}
        res = self.normal_session.post(self.normal_server_url,
                                data,
                                allow_redirects=False,
                                timeout=self.timeout,
                                headers={'Referer': self.normal_server_url})

        # If the response is a redirect and doesnt point to an error message page, then we are logged in
        if not (res.status_code == 200 and res.text.find("/?welcome") > 0):
            raise AuthenticationError("Login to normal server failed")
        else:
            logger.info("Titulky.com: Successfully logged in to normal server, caching cookies for future connections...")
            cache.set('normal_titulky_cookiejar', self.normal_session.cookies.copy())
            # return True

    def logout(self):
        logger.info("Titulky.com: Logging out")

        res = self.premium_session.get(self.premium_logout_url,
                               allow_redirects=False,
                               timeout=self.timeout,
                               headers={'Referer': self.premium_server_url})

        location_qs = parse_qs(urlparse(res.headers['Location']).query)

        res = self.normal_session.get(self.normal_logout_url,
                               allow_redirects=False,
                               timeout=self.timeout,
                               headers={'Referer': self.normal_server_url})

        # location_qs = parse_qs(urlparse(res.headers['Location']).query)

        logger.info("Titulky.com: Clearing cache...")
        cache.delete('premium_titulky_cookiejar')
        cache.delete('normal_titulky_cookiejar')
        cache.delete('titulky_user_agent')

        # If the response is a redirect and doesnt point to an error message page, then we are logged out
        if res.status_code == 302 and location_qs['msg_type'][0] == 'i':
            return True
        else:
            raise AuthenticationError("Logout failed.")

    # GET request a page. This functions acts as a requests.session.get proxy handling expired cached cookies
    # and subsequent relogging and sending the original request again. If all went well, returns the response.
    def get_request(self, url, ref=premium_server_url, allow_redirects=False, _recursion=0):
        # That's deep... recursion... Stop. We don't have infinite memmory. And don't want to
        # spam titulky's server either. So we have to just accept the defeat. Let it throw!
        if _recursion >= 5:
            raise AuthenticationError("Got into a loop and couldn't get authenticated!")

        logger.debug(f"Titulky.com: Fetching url: {url}")

        if url.find(self.premium_server_url) != 0:
            res = self.normal_session.get(
                url,
                timeout=self.timeout,
                allow_redirects=allow_redirects,
                headers={'Referer': quote(ref) if ref else None})  # URL encode ref if it has value
        else:
            res = self.premium_session.get(
                url,
                timeout=self.timeout,
                allow_redirects=allow_redirects,
                headers={'Referer': quote(ref) if ref else None})  # URL encode ref if it has value

        # Check if we got redirected because login cookies expired.
        # Note: microoptimization - don't bother parsing qs for non 302 responses.
        if res.status_code == 302:
            location_qs = parse_qs(urlparse(res.headers['Location']).query)
            if location_qs['msg_type'][0] == 'e' and "Přihlašte se" in location_qs['msg'][0]:
                logger.info(f"Titulky.com: Login premium cookies expired.")
                self.login(True)
                return self.get_request(url, ref=ref, _recursion=(_recursion + 1))

        return res

    def fetch_page(self, url, ref=premium_server_url, allow_redirects=False):
        res = self.get_request(url, ref=ref, allow_redirects=allow_redirects)

        if res.status_code != 200:
            raise HTTPError(f"Fetch failed with status code {res.status_code}")
        if not res.text:
            raise ProviderError("No response returned from the provider")

        return res.text

    def build_url(self, params):
        result = f"{self.premium_server_url}/?"

        for key, value in params.items():
            result += f'{key}={value}&'

        # Remove the last &
        result = result[:-1]

        # Remove spaces
        result = result.replace(' ', '+')

        return result

    # Retrieves the fps value given subtitles id from the details page and caches it.
    def retrieve_subtitles_fps(self, subtitles_id):
        cache_key = f"titulky_subs-{subtitles_id}_fps"
        cached_fps_value = cache.get(cache_key)

        if(cached_fps_value != NO_VALUE):
            logger.debug(f"Titulky.com: Reusing cached fps value {cached_fps_value} for subtitles with id {subtitles_id}")
            return cached_fps_value

        params = {
            'action': 'detail',
            'id': subtitles_id
        }
        browse_url = self.build_url(params)
        html_src = self.fetch_page(browse_url, allow_redirects=True)
        browse_page_soup = ParserBeautifulSoup(html_src, ['lxml', 'html.parser'])

        fps_container = browse_page_soup.select_one("div.ulozil:has(> img[src='img/ico/Movieroll.png'])")
        if(fps_container is None):
            logger.debug("Titulky.com: Could not manage to find the FPS container in the details page")
            cache.set(cache_key, None)
            return None

        fps_text_components = fps_container.get_text(strip=True).split()
        # Check if the container contains valid fps data
        if(len(fps_text_components) < 2 or fps_text_components[1].lower() != "fps"):
            logger.debug(f"Titulky.com: Could not determine FPS value for subtitles with id {subtitles_id}")
            cache.set(cache_key, None)
            return None

        fps_text = fps_text_components[0].replace(",", ".") # Fix decimal comma to decimal point
        try:
            fps = float(fps_text)
            logger.debug(f"Titulky.com: Retrieved FPS value {fps} from details page for subtitles with id {subtitles_id}")
            cache.set(cache_key, fps)
            return fps
        except:
            logger.debug(f"Titulky.com: There was an error parsing FPS value string for subtitles with id {subtitles_id}")
            cache.set(cache_key, None)
            return None


    """ 
        There are multiple ways to find substitles on Titulky.com, however we are 
        going to utilize a page that lists all available subtitles for all episodes in a season
        
        To my surprise, the server in this case treats movies as a tv series with a "0" season and "0" episode
        
        BROWSE subtitles by IMDB ID:
           - Subtitles are here categorised by seasons and episodes
           - URL: https://premium.titulky.com/?action=serial&step=<SEASON>&id=<IMDB ID>
           - it seems that the url redirects to a page with their own internal ID, redirects should be allowed here
    """
    def query(self, languages,
                    media_type,
                    imdb_id,
                    season=0,
                    episode=0):

        params = {
            'action': 'serial',
            # If browsing subtitles for a movie, then set the step parameter to 0
            'step': season,
            # Remove the "tt" prefix
            'id': imdb_id[2:]
        }
        browse_url = self.build_url(params)
        html_src = self.fetch_page(browse_url, allow_redirects=True)

        browse_page_soup = ParserBeautifulSoup(html_src, ['lxml', 'html.parser'])
        # Container element containing subtitle div rows, None if the series was not found or similar
        container = browse_page_soup.find('form', class_='cloudForm')

        # No container with subtitles
        if not container:
            logger.info("Titulky.com: Could not find container element. No subtitles found.")
            return []

        # All rows: subtitle rows, episode number rows, useless rows... Gotta filter this out.
        all_rows = container.find_all('div', class_='row')

        # Filtering and parsing rows
        episodes_dict = {}
        last_ep_num = None
        for row in all_rows:
            # This element holds the episode number of following row(s) of subtitles
            # E.g.: 1., 2., 3., 4.
            number_container = row.find('h5')
            # Link to the sub details
            anchor = row.find('a') if 'pbl1' in row['class'] or 'pbl0' in row['class'] else None

            if number_container:
                # The text content of this container is the episode number
                try:
                    # Remove period at the end and parse the string into a number
                    number_str = number_container.text.strip().rstrip('.')
                    number = int(number_str) if number_str else 0
                    last_ep_num = number
                except:
                    raise ProviderError("Could not parse episode number!")
            elif anchor:
                # The container contains link to details page
                if last_ep_num is None:
                    raise ProviderError("Previous episode number missing, can't parse.")
                
                release_info = anchor.get_text(strip=True)
                if release_info == '???':
                    release_info = ''
                
                details_link = f"{self.premium_server_url}{anchor.get('href')[1:]}"
                
                id_match = re.findall(r'id=(\d+)', details_link)
                sub_id = id_match[0] if len(id_match) > 0 else None
                if "pbl0" in row.get("class"):
                    download_link = f"{self.premium_download_url}{sub_id}"
                else:
                    download_link = f"{self.normal_download_url}{sub_id}"
                # Approved subtitles have a pbl1 class for their row, others have a pbl0 class
                approved = True if 'pbl1' in row.get('class') else False

                uploader = row.contents[5].get_text(strip=True)
                
                # Parse language to filter out subtitles that are not in the desired language
                sub_language = None
                czech_flag = row.select('img[src*=\'flag-CZ\']')
                slovak_flag = row.select('img[src*=\'flag-SK\']')

                if czech_flag and not slovak_flag:
                    sub_language = Language('ces')
                elif slovak_flag and not czech_flag:
                    sub_language = Language('slk')
                else:
                    logger.debug("Titulky.com: Unknown language while parsing subtitles!")
                    continue
                
                # If the subtitles language is not requested
                if sub_language not in languages:
                    logger.debug("Titulky.com: Language not in desired languages, skipping...")
                    continue
                
                # Skip unapproved subtitles if turned on in settings
                if self.approved_only and not approved:
                    logger.debug("Titulky.com: Approved only, skipping...")
                    continue

                result = {
                    'id': sub_id,
                    'release_info': release_info,
                    'approved': approved,
                    'language': sub_language,
                    'uploader': uploader,
                    'details_link': details_link,
                    'download_link': download_link,
                    'fps': self.retrieve_subtitles_fps(sub_id) if self.skip_wrong_fps else None,
                }

                # If this row contains the first subtitles to an episode number,
                # add an empty array into the episodes dict at its place.
                if not last_ep_num in episodes_dict:
                    episodes_dict[last_ep_num] = []

                episodes_dict[last_ep_num].append(result)
        
        # Clean up
        browse_page_soup.decompose()
        browse_page_soup = None
        
        # Rows parsed into episodes_dict, now lets read what we got.
        if not episode in episodes_dict:
            # well, we got nothing, that happens!
            logger.info("Titulky.com: No subtitles found")
            return []

        sub_infos = episodes_dict[episode]

        # After parsing, create new instances of Subtitle class
        subtitles = []
        for sub_info in sub_infos:
            subtitle_instance = self.subtitle_class(
                sub_info['id'],
                imdb_id,
                sub_info['language'],
                season if media_type is SubtitlesType.EPISODE else None,
                episode if media_type is SubtitlesType.EPISODE else None,
                sub_info['release_info'],
                sub_info['uploader'],
                sub_info['approved'],
                sub_info['details_link'],
                sub_info['download_link'],
                sub_info['fps'],
                self.skip_wrong_fps,
                asked_for_episode=(media_type is SubtitlesType.EPISODE),
            )
            subtitles.append(subtitle_instance)

        return subtitles

    def list_subtitles(self, video, languages):
        subtitles = []

        if isinstance(video, Episode):
            if video.series_imdb_id:
                logger.info("Titulky.com: Searching subtitles for a TV series episode")
                subtitles = self.query(languages, SubtitlesType.EPISODE,
                                                    imdb_id=video.series_imdb_id,
                                                    season=video.season,
                                                    episode=video.episode)
            else:
                logger.info(f"Titulky.com: Skipping {video}! No IMDB ID found.")
        elif isinstance(video, Movie):
            if video.imdb_id:
                logger.info("Titulky.com: Searching subtitles for a movie")
                subtitles = self.query(languages, SubtitlesType.MOVIE, imdb_id=video.imdb_id)
            else:
                logger.info(f"Titulky.com: Skipping {video}! No IMDB ID found.")

        return subtitles

    def download_subtitle(self, subtitle):
        if subtitle.download_link.find(self.premium_download_url) != 0:
            for i in range(3):
                logger.debug("Titulky.com: Trying download subtitle %d/3...", i + 1)

                html_src = self.fetch_page(subtitle.download_link, ref=subtitle.page_link)

                down_page = ParserBeautifulSoup(html_src, ['lxml', 'html.parser'])

                captcha_img = down_page.find('img', src='./captcha/captcha.php')
                if captcha_img:
                    logger.debug("Titulky.com: Found CAPTCHA code.")

                    try:
                        # Reading CAPTCHA image
                        res = self.get_request(self.captcha_img_url, ref=subtitle.page_link)

                        res.raise_for_status()
                    except:
                        if i >= 2:
                            raise HTTPError(f"An error occured during reading CAPTCHA image '#{subtitle.id}' - {self.captcha_url} !!!")
                        else:
                            logger.error("Titulky.com: Error in reading CAPTCHA code !!!")
                            continue

                    # Calling anti-captcha
                    pitcher = pitchers.get_pitcher("AntiCaptchaImageProxyLess")("Titulky.com", io.BytesIO(res.content),
                                                     user_agent=self.normal_session.headers["User-Agent"],
                                                     cookies=self.normal_session.cookies.get_dict(),
                                                     is_invisible=True)

                    captcha_code = pitcher.throw().replace("0", "O").strip()
                    logger.debug("Titulky.com: CAPTCHA code: '%s'", captcha_code)
                    if not captcha_code:
                        logger.error("Titulky.com: Couldn't solve CAPTCHA code !!!")
                        continue

                    try:
                        # Sending captcha code
                        data = {'downkod': captcha_code, 'securedown': "2", "zip": "", "T": "1-1652287319136", "titulky": subtitle.id, "histstamp": ""}
                        res = self.normal_session.post(self.captcha_url,
                                                data,
                                                allow_redirects=False,
                                                timeout=self.timeout,
                                                headers={'Referer': self.normal_server_url})

                        res.raise_for_status()
                    except:
                        if i >= 2:
                            raise HTTPError(f"An error occured during sending CAPTCHA code '#{subtitle.id}' - {self.captcha_url} !!!")
                        else:
                            logger.error("Titulky.com: Error in sending CAPTCHA code !!!")
                            continue

                    down_page = ParserBeautifulSoup(res.text, ['lxml', 'html.parser'])

                    start_pos = down_page.text.find("CHYBA -")
                    if (start_pos >= 0):
                        error_mssage = down_page.text[start_pos:]
                        end_pos = error_mssage.find("\n")
                        if end_pos <= 0:
                            end_pos = 40

                        error_mssage = error_mssage[0: end_pos]
                        logger.error("Titulky.com: Error in CAPTCHA code: %s !!!", error_mssage)
                        continue
                    else:
                        break

            down_url_link = down_page.find('a', id='downlink')
            if not down_url_link:
                logger.error("Titulky.com: Cannot find downlink (%s) !!!", subtitle.download_link)
                return

            down_url = "https://" + down_url_link.contents[0].strip()

            delay = down_page.find('body').decode_contents()

            if delay != None and "CountDown" in delay and delay.find("CountDown(") != -1:
                cd_start = delay.find("CountDown(") + 10
                delay = int(delay[cd_start : delay.find(")", cd_start)]) + 0.5
                logger.debug(f"Titulky.com: Delay {delay}s before downloading.")
                time.sleep(delay)

            try:
                # Calling download subtitle
                res = self.get_request(down_url, ref=subtitle.page_link)

                res.raise_for_status()
            except:
                raise HTTPError(f"Titulky.com: Error downloading subtitle from normal serer !!! '{down_url}'")
        else:
            res = self.get_request(subtitle.download_link, ref=subtitle.page_link)

            try:
                res.raise_for_status()
            except:
                logger.error(f"Titulky.com: Error downloading subtitle from premium server !!! '{subtitle.download_link}'")

        archive_stream = io.BytesIO(res.content)
        archive = None
        if rarfile.is_rarfile(archive_stream):
            logger.debug("Titulky.com: Identified rar archive")
            archive = rarfile.RarFile(archive_stream)
            subtitle_content = self.get_subtitle_from_archive(subtitle, archive)
        elif zipfile.is_zipfile(archive_stream):
            logger.debug("Titulky.com: Identified zip archive")
            archive = zipfile.ZipFile(archive_stream)
            subtitle_content = self.get_subtitle_from_archive(subtitle, archive)
        else:
            subtitle_content = fix_line_ending(res.content)

        if subtitle_content:
            subtitle.content = subtitle_content
        else:
            logger.error("Titulky.com: Subtitle is empty (%s) !!!", subtitle.download_link)
