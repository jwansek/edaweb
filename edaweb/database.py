from urllib.parse import urlparse
from dataclasses import dataclass
from lxml import html
import configparser
import threading
import services
import operator
import datetime
import requests
import twython
import pymysql
import random
import os
import re

@dataclass
class Database:
    safeLogin:bool = True   #automatically login with the user in the config file, who is read only
    user:str = None         #otherwise, login with the given username and passwd
    passwd:str = None

    def __enter__(self):
        config_path = os.path.join(os.path.dirname(__file__), "..", "edaweb.conf")
        if not os.path.exists(config_path):
            raise FileNotFoundError("Could not find edaweb.conf config file")
        self.config = configparser.ConfigParser(interpolation = None)
        self.config.read(config_path)

        if self.safeLogin:
            self.__connection = pymysql.connect(
                **self.config["mysql"],
                charset = "utf8mb4"
            )
        else:
            self.__connection = pymysql.connect(
                user = self.user,
                passwd = self.passwd,
                host = self.config["mysql"]["host"],
                db = self.config["mysql"]["db"],
                charset = "utf8mb4"
            )
        return self

    def __exit__(self, type, value, traceback):
        self.__connection.commit()
        self.__connection.close()

    def get_header_links(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT name, link FROM headerLinks WHERE display = true ORDER BY name;")
            return cursor.fetchall()

    def get_image(self, imageName):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT alt, url FROM images WHERE imageName = %s;", (imageName, ))
            return cursor.fetchone()

    def get_pfp_images(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT alt, url FROM images WHERE pfp_img = 1;")
            return cursor.fetchall()

    def get_sidebar_images(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT alt, url FROM images WHERE sidebar_image = 1;")
            return cursor.fetchall()

    def get_header_articles(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT articleName, link FROM headerArticles WHERE display = true;")
            return cursor.fetchall()

    def get_all_categories(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT category_name FROM categories;")
            return [i[0] for i in cursor.fetchall()]

    def add_category(self, category):
        if not category in self.get_all_categories():
            with self.__connection.cursor() as cursor:
                cursor.execute("INSERT INTO categories (category_name) VALUES (%s);", (category, ))

            self.__connection.commit()
            return True
            
        return False

    def add_thought(self, category, title, markdown):
        with self.__connection.cursor() as cursor:
            cursor.execute("""
            INSERT INTO thoughts (category_id, title, markdown_text) 
            VALUES ((
                SELECT category_id FROM categories WHERE category_name = %s
            ), %s, %s);""", (category, title, markdown))
        self.__connection.commit()

    def get_thought(self, id_):
        with self.__connection.cursor() as cursor:
            cursor.execute("""
            SELECT categories.category_name, thoughts.title, thoughts.dt, thoughts.markdown_text, thoughts.redirect 
            FROM thoughts INNER JOIN categories 
            ON thoughts.category_id = categories.category_id 
            WHERE thought_id = %s;""", (id_, ))
            return cursor.fetchone()

    def get_similar_thoughts(self, category, id_):
        with self.__connection.cursor() as cursor:
            cursor.execute("""
            SELECT thought_id, title, dt, category_name FROM thoughts 
            INNER JOIN categories ON thoughts.category_id = categories.category_id 
            WHERE category_name = %s AND thought_id != %s;""", 
            (category, id_))
            return cursor.fetchall()

    def get_featured_thoughts(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT thought_id, title FROM thoughts WHERE featured = 1;")
            return cursor.fetchall()

    def update_thought_markdown(self, id_, markdown):
        with self.__connection.cursor() as cursor:
            cursor.execute("UPDATE thoughts SET markdown_text = %s WHERE thought_id = %s;", (markdown, id_))
        self.__connection.commit()

    def get_categories_not(self, category_name):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT category_name FROM categories WHERE category_name != %s;", (category_name, ))
            return [i[0] for i in cursor.fetchall()]

    def get_all_thoughts(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("""
            SELECT thought_id, title, dt, category_name FROM thoughts 
            INNER JOIN categories ON thoughts.category_id = categories.category_id;
            """)
            return cursor.fetchall()

    def get_cached_tweets(self, numToGet = None):
        with self.__connection.cursor() as cursor:
            sql = "SELECT tweet, tweet_id, account FROM diary WHERE account = %s ORDER BY tweeted_at DESC"
            args = (self.config.get("twitter", "main_account"), )
            if numToGet is not None:
                sql += " LIMIT %s;"
                args = (self.config.get("twitter", "main_account"), numToGet)
            else:
                sql += ";"
            cursor.execute(sql, args)

            return [(i[0], "https://%s/%s/status/%d" % (self.config.get("nitter", "outsideurl"), i[2], i[1])) for i in cursor.fetchall()]

    def get_cached_commits(self, since = None, recurse = True):
        with self.__connection.cursor() as cursor:
            if since is not None:
                cursor.execute("SELECT DISTINCT message, url, commitTime, additions, deletions, total FROM commitCache WHERE commitTime > %s ORDER BY commitTime DESC;", (since, ))
            else:
                cursor.execute("SELECT DISTINCT message, url, commitTime, additions, deletions, total FROM commitCache ORDER BY commitTime DESC;")
            # i think i might have spent too long doing functional programming
            return [{
                "repo": urlparse(i[1]).path.split("/")[2],
                "github_repo_url": "https://github.com" + "/".join(urlparse(i[1]).path.split("/")[:3]),
                "git_repo_url": "https://%s/%s.git/about" % (self.config.get("github", "personal_domain"), urlparse(i[1]).path.split("/")[2]),
                "message": i[0],
                "github_commit_url": i[1],
                "git_commit_url": "https://%s/%s.git/commit/?id=%s" % (
                    self.config.get("github", "personal_domain"), 
                    urlparse(i[1]).path.split("/")[2], 
                    urlparse(i[1]).path.split("/")[-1]
                ),
                "datetime": i[2].timestamp(),
                "stats": {
                    "additions": i[3],
                    "deletions": i[4],
                    "total": i[5]
                }
            } for i in cursor.fetchall()]

    def update_commit_cache(self, requested):
        with self.__connection.cursor() as cursor:
            for commit in requested:
                cursor.execute("SELECT DISTINCT url FROM commitCache;")
                urls = [i[0] for i in cursor.fetchall()]

                if commit["url"] not in urls:
                    cursor.execute("""
                    INSERT INTO commitCache (message, url, commitTime, additions, deletions, total)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (commit["message"], commit["url"], commit["datetime"], commit["stats"]["additions"], commit["stats"]["deletions"], commit["stats"]["total"])
                )
        self.__connection.commit()

    def get_last_commit_time(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT MAX(commitTime) FROM commitCache;")
            return cursor.fetchone()[0]

    def get_my_twitter(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT link FROM headerLinks WHERE name = 'twitter';")
            return cursor.fetchone()[0]

    def get_my_diary_twitter(self):
        return self.config.get("twitter", "diary_account")

    def get_iso_cd_options(self):
        iso_dir = self.config.get("cds", "location")
        return [
            i
            for i in os.listdir(iso_dir)
            if os.path.splitext(i)[-1].lower() in [".iso"]
            and os.path.getsize(os.path.join(iso_dir, i)) < self.config.getint("cds", "maxsize")
        ]

    def append_cd_orders(self, iso, email, house, street, city, county, postcode, name):
        with self.__connection.cursor() as cursor:
            cursor.execute("""
            INSERT INTO cd_orders_2 (iso, email, house, street, city, county, postcode, name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (iso, email, house, street, city, county, postcode, name))
            id_ = cursor.lastrowid
        self.__connection.commit()
        return id_

    def append_qnas(self, qnas):
        with self.__connection.cursor() as cursor:
            for qna in qnas:
                cursor.execute("SELECT curiouscat_id FROM qnas WHERE curiouscat_id = %s;", (qna["id"], ))
                if cursor.fetchone() is None:

                    cursor.execute("INSERT INTO `qnas` VALUES (%s, %s, %s, %s, %s, %s);", (
                        qna["id"], qna["link"], qna["datetime"], qna["question"], qna["answer"], qna["host"]
                    ))
                    print("Appended question with timestamp %s" % qna["datetime"].isoformat())

                else:
                    print("Skipped question with timestamp %s" % qna["datetime"].isoformat())
        self.__connection.commit()

    def get_oldest_qna(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT MAX(timestamp) FROM qnas;")
            return cursor.fetchone()[0]

    def get_qnas(self):
        with self.__connection.cursor() as cursor:
            cursor.execute("SELECT * FROM qnas;")
            return sorted(cursor.fetchall(), key = operator.itemgetter(2), reverse = True)


    


