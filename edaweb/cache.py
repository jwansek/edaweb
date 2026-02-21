import database
import services
import json

def update_cache():
    print("Updating cache...")
    with database.Database() as db:
        db.update_commit_cache(services.request_recent_commits(since = db.get_last_commit_time()))
        print("Finished adding github commits...")
        db.append_qnas(services.scrape_whispa(db.config.get("qnas", "url"), since = db.get_oldest_qna()))
        # print(json.dumps(services.scrape_whispa(db.config.get("qnas", "url"), since = db.get_oldest_qna()), indent = 4))
        print("Finished parsing Q&As...")

    print("Started getting docker information with SSH...")
    print(services.cache_all_docker_containers(services.CONFIG.get("ssh", "docker_key_path")))
    print("Finished caching.")


if __name__ == "__main__":
    update_cache()