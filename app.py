import configparser
import database
import services
import flask

app = flask.Flask(__name__)
CONFIG = configparser.ConfigParser()
CONFIG.read("edaweb.conf")

def get_template_items(title, db):
    return {
        "links": db.get_header_links(),
        "image": db.get_image("telegrampic"),
        "title": title,
        "articles": db.get_header_articles()
    }

@app.route("/")
def index():
    with database.Database() as db:
        return flask.render_template(
            "index.html", 
            **get_template_items("edaweb.co.uk", db)
        )

@app.route("/discord")
def discord():
    with database.Database() as db:
        return flask.render_template(
            "discord.html", 
            **get_template_items("discord", db),
            discord = CONFIG["discord"]["username"]
        )

@app.route("/services")
def serve_services():
    with database.Database() as db:
        return flask.render_template(
            "services.html",
            **get_template_items("services", db),
            docker = services.get_docker_stats(),
            qbit = services.get_qbit_stats(),
            trans = services.get_trans_stats(),
            pihole = services.get_pihole_stats()
        )

if __name__ == "__main__":
    app.run(host = "0.0.0.0", debug = True)