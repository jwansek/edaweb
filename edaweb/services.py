from dataclasses import dataclass
from io import StringIO
from lxml import html, etree
from github import Github
import multiprocessing
import paramiko.client
from APiHole import PiHole
import transmission_rpc
import configparser
import math as maths
import requests
import datetime
import urllib
import docker
import random
import subprocess
import fabric
import pickle
import queue
import json
import time
import os

theLastId = 0
config_path = os.path.join(os.path.dirname(__file__), "..", "edaweb.conf")
if not os.path.exists(config_path):
    raise FileNotFoundError("Could not find edaweb.conf config file")
CONFIG = configparser.ConfigParser(interpolation = None)
CONFIG.read(config_path)

def humanbytes(B):
   'Return the given bytes as a human friendly KB, MB, GB, or TB string'
   B = float(B)
   KB = float(1024)
   MB = float(KB ** 2) # 1,048,576
   GB = float(KB ** 3) # 1,073,741,824
   TB = float(KB ** 4) # 1,099,511,627,776

   if B < KB:
      return '{0} {1}'.format(B,'Bytes' if 0 == B > 1 else 'Byte')
   elif KB <= B < MB:
      return '{0:.2f} KB'.format(B/KB)
   elif MB <= B < GB:
      return '{0:.2f} MB'.format(B/MB)
   elif GB <= B < TB:
      return '{0:.2f} GB'.format(B/GB)
   elif TB <= B:
      return '{0:.2f} TB'.format(B/TB)

@dataclass
class SafebooruImage:
    id_: int
    url: str
    searchTags: list
    tags: list
    source: str
    imurl: str

    def remove_tag(self, tag):
        return list(set(self.searchTags).difference(set([tag])))

@dataclass
class DownloadedImage:
    imurl: str
    
    def __enter__(self):
        self.filename = os.path.join("static", "images", "random.jpg")

        req = urllib.request.Request(self.imurl, headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_5_8) AppleWebKit/534.50.2 (KHTML, like Gecko) Version/5.0.6 Safari/533.22.3'})
        mediaContent = urllib.request.urlopen(req).read()
        with open(self.filename, "wb") as f:
            f.write(mediaContent)
        return self.filename

    def __exit__(self, type, value, traceback):
        os.remove(self.filename)

def get_num_pages(tags):
    pages_url = "https://safebooru.org/index.php?page=post&s=list&tags=%s" % "+".join(tags)
    tree = html.fromstring(requests.get(pages_url).content)
    try:
        finalpage_element = tree.xpath("/html/body/div[6]/div/div[2]/div[2]/div/a[12]")[0]
    except IndexError:
        return 1
    else:
        return int(int(urllib.parse.parse_qs(finalpage_element.get("href"))["pid"][0]) / (5*8))

def get_id_from_url(url):
    return int(urllib.parse.parse_qs(url)["id"][0])

def get_random_image(tags):
    global theLastId
    searchPage = random.randint(1, get_num_pages(tags)) * 5 * 8
    url = "https://safebooru.org/index.php?page=post&s=list&tags=%s&pid=%i" % ("+".join(tags), searchPage)
    tree = html.fromstring(requests.get(url).content)

    imageElements = [e for e in tree.xpath("/html/body/div[6]/div/div[2]/div[1]")[0].iter(tag = "a")]
    try:
        element = random.choice(imageElements)
    except IndexError:
        # raise ConnectionError("Couldn't find any images")
        return get_random_image(tags)

    url = "https://safebooru.org/" + element.get("href")
    if get_id_from_url(url) == theLastId:
        return get_random_image(tags)
    theLastId = get_id_from_url(url)

    try:
        sbi = SafebooruImage(
            id_ = get_id_from_url(url),
            url = url,
            tags = element.find("img").get("alt").split(),
            searchTags = tags,
            source = fix_source_url(get_source(url)),
            imurl = get_imurl(url)
        )
    except (ConnectionError, KeyError) as e:
        print("[ERROR]", e)
        return get_random_image(tags)

    if link_deleted(sbi.url):
        print("Retried since the source was deleted...")
        return get_random_image(tags)

    return sbi

def get_source(url):
    tree = html.fromstring(requests.get(url).content)
    for element in tree.xpath('//*[@id="stats"]')[0].iter("li"):
        if element.text.startswith("Source: h"):
            return element.text[8:]
        elif element.text.startswith("Source:"):
            for child in element.iter():
                if child.get("href") is not None:
                    return child.get("href")
    raise ConnectionError("Couldn't find source image for id %i" % get_id_from_url(url))

def fix_source_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc == "www.pixiv.net":
        return "https://www.pixiv.net/en/artworks/" + urllib.parse.parse_qs(parsed.query)["illust_id"][0]
    elif parsed.netloc in ["bishie.booru.org", "www.secchan.net"]:
        return ConnectionError("Couldn't get source")
    elif "pximg.net" in parsed.netloc or "pixiv.net" in parsed.netloc:
        return "https://www.pixiv.net/en/artworks/" + parsed.path.split("/")[-1][:8]
    elif parsed.netloc == "twitter.com":
        return url.replace("twitter.com", "nitter.eda.gay")
    return url

def get_imurl(url):
    tree = html.fromstring(requests.get(url).content)
    return tree.xpath('//*[@id="image"]')[0].get("src")

def link_deleted(url):
    text = requests.get(url).text
    return text[text.find("<title>") + 7 : text.find("</title>")] in ["Error | nitter", "イラストコミュニケーションサービス[pixiv]"]

def request_recent_commits(since = datetime.datetime.now() - datetime.timedelta(days=7)):
    g = Github(CONFIG.get("github", "access_code"))
    out = []
    for repo in g.get_user().get_repos():
        # print(repo.name, list(repo.get_branches()))
        try:
            for commit in repo.get_commits(since = since):
                out.append({
                    "repo": repo.name,
                    "message": commit.commit.message,
                    "url": commit.html_url,
                    "datetime": commit.commit.author.date,
                    "stats": {
                        "additions": commit.stats.additions,
                        "deletions": commit.stats.deletions,
                        "total": commit.stats.total
                    }
                })
        except Exception as e:
            print(repo, e)

    return sorted(out, key = lambda a: a["datetime"], reverse = True) 

def scrape_nitter(username, get_until:int):
    new_tweets = []
    nitter_url = CONFIG.get("nitter", "internalurl")
    nitter_port = CONFIG.getint("nitter", "internalport")
    scrape_new_pages = True
    url = "http://%s:%d/%s" % (nitter_url, nitter_port, username)

    while scrape_new_pages:
        tree = html.fromstring(requests.get(url).content)
        for i, tweetUrlElement in enumerate(tree.xpath('//*[@class="tweet-link"]'), 0):
            if i > 0 and tweetUrlElement.get("href").split("/")[1] == username:
                id_ = int(urllib.parse.urlparse(tweetUrlElement.get("href")).path.split("/")[-1])
                tweet_link = "http://%s:%d%s" % (nitter_url, nitter_port, tweetUrlElement.get("href"))

                if id_ == get_until:
                    scrape_new_pages = False
                    break

                try:
                    dt, replying_to, text, images = parse_tweet(tweet_link)
                    new_tweets.append((id_, dt, replying_to, text, username, images))
                    print(dt, "'%s'" % text)
                except IndexError:
                    print("Couldn't get any more tweets")
                    scrape_new_pages = False
                    break
                except ConnectionError:
                    print("Rate limited, try again later")
                    return []


        try:
            cursor = tree.xpath('//*[@class="show-more"]/a')[0].get("href")
        except IndexError:
            # no more elements
            break
        url = "http://%s:%d/%s%s" % (nitter_url, nitter_port, username, cursor)

    return new_tweets

def parse_tweet(tweet_url):
    # print(tweet_url)
    tree = html.fromstring(requests.get(tweet_url).content)
    # with open("2images.html", "r") as f:
    #     tree = html.fromstring(f.read())

    rate_limited_elem = tree.xpath("/html/body/div/div/div/span")
    if rate_limited_elem != []:
        if rate_limited_elem[0].text == "Instance has been rate limited.":
            raise ConnectionError("Instance has been rate limited.")

    main_tweet_elem = tree.xpath('//*[@class="main-tweet"]')[0]

    dt_str = main_tweet_elem.xpath('//*[@class="tweet-published"]')[0].text
    dt = datetime.datetime.strptime(dt_str.replace("Â", ""), "%b %d, %Y · %I:%M %p UTC")
    text = tree.xpath('//*[@class="main-tweet"]/div/div/div[2]')[0].text_content() 
    if text == "":
        text = "[Image only]"
    replying_to_elems = tree.xpath('//*[@class="before-tweet thread-line"]/div/a')
    if replying_to_elems != []:
        replying_to = int(urllib.parse.urlparse(replying_to_elems[-1].get("href")).path.split("/")[-1])
    else:
        replying_to = None
        
    images = []
    images_elems = tree.xpath('//*[@class="main-tweet"]/div/div/div[3]/div/div/a/img')
    for image_elem in images_elems:
        images.append("https://" + CONFIG.get("nitter", "outsideurl") + urllib.parse.urlparse(image_elem.get("src")).path)

    return dt, replying_to, text, images

def scrape_whispa(whispa_url, since = None):
    def query_answer(answer_url, max_retries = 10):
        for i in range(max_retries):
            try:
                return requests.get(answer_url)
            except requests.exceptions.ConnectionError:
                s = 5.05 * (i + 1)
                print("Connection timed out, retrying in %.2fs" % s)
                time.sleep(s)
                continue

    # add a bit of wiggle room in case i don't answer the questions in order (i often do this)
    if since is None:
        stop_at = datetime.datetime(year = 2001, month = 8, day = 12)
    else:
        stop_at = since - datetime.timedelta(days = 14)
        print("The newest Q&A timestamp in the database was %s, we will stop looking at %s." % (since.astimezone().isoformat(), stop_at.astimezone().isoformat()))

    html_ = requests.get(whispa_url).content.decode()
    # with open("temp.html", "w") as f:
    #     f.write(html_)

    tree = html.fromstring(html_)
    qnas = []
    # we're not doing proper HTML scraping here really... since the site uses client side rendering
    # we rather parse the JS scripts to get the JSON payload of useful information... sadly this looks horrible
    for i, script in enumerate(tree.xpath("/html/body/script"), 0):
        js = str(script.text)
        if "receivedFeedback" in js:
            # my god this is horrible...
            parsed_json = json.loads(json.loads(js[19:-1])[1][2:])[0][3]["loadedUser"]["receivedFeedback"]
            # print(json.dumps(parsed_json, indent = 4))
            # with open("whispas_%i.json" % i, "w") as f:
            #     json.dump(parsed_json, f, indent = 4)
            for j in parsed_json:
                if j["_count"]["childFeedback"] < 0:
                    continue

                answer_url = "https://apiv4.whispa.sh/feedbacks/%s/children/public" % j["id"]
                req = query_answer(answer_url)
                try:
                    firstanswer = req.json()["data"][0]
                except IndexError:
                    continue
                dt = datetime.datetime.fromisoformat(firstanswer["createdAt"][:-1])

                qna = {
                    # "id": int(j["id"], base = 16),
                    "id": int(dt.timestamp()),
                    "link": answer_url,
                    "datetime": dt,
                    "question": j["content"],
                    "answer": firstanswer["content"],
                    "host": "whispa.sh"
                }
                print(qna)     
                qnas.append(qna)
                time.sleep(2.03)
                if dt <= stop_at:
                    print("Met the threshold for oldest Q&A, so stopped looking.")
                    break
    return qnas

def get_docker_containers(host, ssh_key_path):
    result = fabric.Connection(
        host = host,
        user = "root",
        connect_kwargs = {
            "key_filename": ssh_key_path,
            "look_for_keys": False
        }
    ).run('docker ps -a -s --format "table {{.Names}};{{.Status}};{{.Image}}"', hide = True)
    return [line.split(";") for line in result.stdout.split("\n")[1:-1]]

def cache_all_docker_containers(ssh_key_path):
    containers = {}
    containers["containers"] = {}
    for host, name in CONFIG["docker_hosts"].items():
        print(host)
        containers["containers"][(host, name)] = get_docker_containers(host, ssh_key_path)

    containers["cachetime"] = "Docker information last updated at %s" % str(datetime.datetime.now())
    with open("/tmp/docker-cache.json", "wb") as f:
        pickle.dump(containers, f)

def get_all_docker_containers():
    if not os.path.exists("/tmp/docker-cache.json"):
        return {"containers": {}, "cachetime": "No cached docker information"}

    with open("/tmp/docker-cache.json", "rb") as f:
        return pickle.load(f)

def timeout(func):
    # cant get this to work with queue.Queue() for some reason?
    # this works but Manager() uses an extra thread than Queue()
    manager = multiprocessing.Manager()
    returnVan = manager.list()
    # ti = time.time()
   
    def runFunc(q, func):
        q.append(func())

    def beginTimeout():
        t = multiprocessing.Process(target = runFunc, args = (returnVan, func))
        t.start()

        t.join(timeout = CONFIG["servicetimeout"].getint("seconds"))

        # print("Request took:", time.time() - ti)
        try:
            return returnVan[0]
        except IndexError:
            if t.is_alive():
                t.terminate()

    return beginTimeout

@timeout
def get_torrent_stats():
    client = transmission_rpc.client.Client(
        host = CONFIG.get("transmission", "host")
    )
    s = vars(client.session_stats())["fields"]
    return {
        "Active torrents:": s["activeTorrentCount"],
        "Downloaded:": humanbytes(s["cumulative-stats"]["downloadedBytes"]),
        "Uploaded:": humanbytes(s["cumulative-stats"]["uploadedBytes"]),
        "Active time:": str(datetime.timedelta(seconds = s["cumulative-stats"]["secondsActive"])),
        "Files added:": s["cumulative-stats"]["filesAdded"],
        "Current upload speed:": humanbytes(s["uploadSpeed"]) + "s/S",
        "Current download speed:": humanbytes(s["downloadSpeed"]) + "s/S"
    }

@timeout
def get_pihole_stats():
    return PiHole.GetSummary(CONFIG.get("pihole", "url"), CONFIG.get("pihole", "key"), True)

def get_recent_commits(db, max_per_repo = 3):
    cache = db.get_cached_commits()
    num_per_repo = {}
    out = []
    for commit in cache:
        if commit["repo"] not in num_per_repo.keys():
            num_per_repo[commit["repo"]] = 0

        num_per_repo[commit["repo"]] += 1
        if num_per_repo[commit["repo"]] <= max_per_repo:
            out.append(commit)

    return sorted(out, key = lambda a: a["datetime"], reverse = True)

if __name__ == "__main__":
    print(scrape_whispa(CONFIG.get("qnas", "url")))
    # import database

    # with database.Database() as db:
    #     print(json.dumps(get_recent_commits(db), indent=4))
