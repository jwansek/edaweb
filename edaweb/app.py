from paste.translogger import TransLogger
from waitress import serve
from PIL import Image
import configparser
import transmission_rpc
import downloader
import datetime
import database
import services
import urllib
import random
import parser
import flask
import sys
import os
import io

app = flask.Flask(__name__)
CONFIG = configparser.ConfigParser(interpolation = None)
CONFIG.read(os.path.join(os.path.dirname(__file__), "edaweb.conf"))
shown_images = set()
shown_sidebar_images = set()

def get_pfp_img(db:database.Database):
    global shown_images
    dbimg = db.get_pfp_images()
    if len(shown_images) == len(dbimg):
        shown_images = set()
    folder = set(dbimg).difference(shown_images)
    choice = random.choice(list(folder))
    shown_images.add(choice)
    return choice

def get_sidebar_img(db:database.Database):
    global shown_sidebar_images
    dbimg = db.get_sidebar_images()
    if len(shown_sidebar_images) == len(dbimg):
        shown_sidebar_images = set()
    folder = set(dbimg).difference(shown_sidebar_images)
    choice = random.choice(list(folder))
    shown_sidebar_images.add(choice)
    return choice

def get_correct_article_headers(db:database.Database, title):
    db_headers = list(db.get_header_articles())
    if title in [i[0] for i in db_headers]:
        out = []
        for i in db_headers:
            if i[0] != title:
                out.append(i)
        return out + [("index", "/~")]
    else:
        return db_headers + [("index", "/~")]

def get_template_items(title, db):
    return {
        "links": db.get_header_links(),
        "image": get_pfp_img(db),
        "title": title,
        "articles": get_correct_article_headers(db, title)
    }

@app.route("/")
@app.route("/~")
def index():
    with database.Database() as db:
        with open(os.path.join(os.path.dirname(__file__), "static", "index.md"), "r") as f:
            return flask.render_template(
                "index.html.j2", 
                **get_template_items("eden's site :3", db),
                days_till_ffs = datetime.datetime(2025, 11, 8) - datetime.datetime.now(),
                markdown = parser.parse_text(f.read())[0],
                featured_thoughts = db.get_featured_thoughts(),
                commits = services.get_recent_commits(db)[:15],
                sidebar_img = get_sidebar_img(db)
            )

@app.route("/robots.txt")
def robots():
    return flask.send_from_directory("static", "robots.txt")

@app.route("/services")
def serve_services():
    with database.Database() as db:
        return flask.render_template(
            "services.html.j2",
            **get_template_items("services", db),
            docker = services.get_all_docker_containers(),
            trans = services.get_torrent_stats(),
            pihole = services.get_pihole_stats()
        )

@app.route("/discord")
def discord():
    with database.Database() as db:
        return flask.render_template(
            "discord.html.j2", 
            **get_template_items("discord", db),
            discord = CONFIG["discord"]["username"]
        )

@app.route("/thought")
def get_thought():
    thought_id = flask.request.args.get("id", type=int)
    with database.Database() as db:
        try:
            category_name, title, dt, parsed, headers, redirect = parser.get_thought_from_id(db, thought_id)
            # print(headers)
        except TypeError:
            flask.abort(404)
            return

        if redirect is not None:
            return flask.redirect(redirect, code = 301)

        return flask.render_template(
            "thought.html.j2",
            **get_template_items(title, db),
            md_html = parsed,
            contents_html = headers,
            dt = "published: " + str(dt),
            category = category_name,
            othercategories = db.get_categories_not(category_name),
            related = db.get_similar_thoughts(category_name, thought_id)
        )

@app.route("/thoughts")
def get_thoughts():
    with database.Database() as db:
        all_ = db.get_all_thoughts()
        tree = {}
        for id_, title, dt, category in all_:
            if category not in tree.keys():
                tree[category] = [(id_, title, dt)]
            else:
                tree[category].append((id_, title, str(dt)))

        return flask.render_template(
            "thoughts.html.j2",
            **get_template_items("thoughts", db),
            tree = tree
        )

@app.route("/img/<filename>")
def serve_image(filename):
    imdirpath = os.path.join(os.path.dirname(__file__), "static", "images")
    if filename in os.listdir(imdirpath):
        try:
            w = int(flask.request.args['w'])
            h = int(flask.request.args['h'])
        except (KeyError, ValueError):
            return flask.send_from_directory(imdirpath, filename)

        img = Image.open(os.path.join(imdirpath, filename))
        img.thumbnail((w, h), Image.LANCZOS)
        io_ = io.BytesIO()
        img.save(io_, format='JPEG')
        return flask.Response(io_.getvalue(), mimetype='image/jpeg')
    else:
        flask.abort(404)

@app.route("/nhdl")
def serve_nhdl():
    with database.Database() as db:
        try:
            nhentai_id = int(flask.request.args["id"])
            with downloader.CompressedImages(nhentai_id) as zippath:
                # return app.send_static_file(os.path.split(zippath)[-1])
                return flask.redirect("/zip/%s" % os.path.split(zippath)[-1])

        except (KeyError, ValueError):
            return flask.render_template(
                "nhdl.html.j2",
                **get_template_items("Hentai Downloader", db)
            )

@app.route("/isocd")
def serve_iso_form():
    with database.Database() as db:
        return flask.render_template(
            "isocd.html.j2",
            **get_template_items("Get a GNU/Linux install CD", db),
            iso_options = db.get_iso_cd_options()
        )

@app.route("/zip/<zipfile>")
def serve_zip(zipfile):
    return flask.send_from_directory(os.path.join(os.path.dirname(__file__), "static", "zips"), zipfile)

@app.route("/pdf/<pdfname>")
def serve_pdf(pdfname):
    return flask.send_from_directory(os.path.join(os.path.dirname(__file__), "static", "papers"), pdfname)

@app.route("/nhdlredirect", methods = ["POST"])
def redirect_nhdl():
    req = dict(flask.request.form)
    try:
        return flask.redirect("/nhdl?id=%i" % int(req["number_input"]))
    except (TypeError, ValueError, KeyError):
        flask.abort(400)
        
@app.route("/getisocd", methods = ["POST"])
def get_iso_cd():
    req = dict(flask.request.form)
    print(req)
    with database.Database() as db:
        id_ = db.append_cd_orders(**req)
        print(id_)
        return flask.render_template(
            "isocd_confirmation.html.j2",
            **get_template_items("Get a GNU/Linux install CD", db),
            email = req["email"],
            req = req,
            id_ = id_
        )

#@app.route("/random")
#def serve_random():
#    try:
#        tags = flask.request.args['tags'].split(" ")
#    except KeyError:
#        flask.abort(400)
#    
#    sbi = services.get_random_image(tags)
#    req = urllib.request.Request(sbi.imurl)
#    mediaContent = urllib.request.urlopen(req).read()
#    with open(os.path.join(os.path.dirname(__file__), "static", "images", "random.jpg"), "wb") as f:
#        f.write(mediaContent)
#
#    with database.Database() as db:
#        return flask.render_template(
#            "random.html.j2",
#            **get_template_items("random image", db),
#            sbi = sbi,
#            localimg = "/img/random.jpg?seed=%i" % random.randint(0, 9999)
#        )

@app.route("/questions")
def serve_questions():
    with database.Database() as db:
        return flask.render_template(
            "questions.html.j2",
            **get_template_items("questions and answers", db),
            qnas_link = CONFIG.get("qnas", "url"),
            qnas = db.get_qnas()
        )

if __name__ == "__main__":
    try:
        if sys.argv[1] == "--production":
            #serve(TransLogger(app), host='127.0.0.1', port = 6969)
            serve(TransLogger(app), host='0.0.0.0', port = 6969, threads = 32)
        else:
            app.run(host = "0.0.0.0", port = 5001, debug = True)
    except IndexError:
        app.run(host = "0.0.0.0", port = 5001, debug = True)
