from datetime import datetime, timezone

import doc_mongo

MSG_SCHEMA = {"$jsonSchema": {"bsonType": "object",
    "required": ["user_id", "session_id", "role", "content", "created_at"],
    "properties": {"user_id": {"bsonType": "string"}, "session_id": {"bsonType": "string"},
                   "role": {"enum": ["user", "assistant"]}, "content": {"bsonType": "string"},
                   "created_at": {"bsonType": "date"}}}}
SUM_SCHEMA = {"$jsonSchema": {"bsonType": "object",
    "required": ["user_id", "session_id", "kind", "content", "created_at"],
    "properties": {"kind": {"enum": ["session", "lifetime"]}, "content": {"bsonType": "string"},
                   "user_msgs_covered": {"bsonType": "int"}, "created_at": {"bsonType": "date"}}}}
EPI_SCHEMA = {"$jsonSchema": {"bsonType": "object",
    "required": ["user_id", "fact", "embedding", "created_at"],
    "properties": {"fact": {"bsonType": "string"}, "embedding": {"bsonType": "array"},
                   "created_at": {"bsonType": "date"}}}}


def now():
    return datetime.now(timezone.utc)


def ensure_memory_collections():
    db = doc_mongo.get_db()
    doc_mongo.ensure_collection(db, "messages", MSG_SCHEMA)
    doc_mongo.ensure_collection(db, "summaries", SUM_SCHEMA)
    doc_mongo.ensure_collection(db, "episodes", EPI_SCHEMA)
    db.messages.create_index([("user_id", 1), ("session_id", 1), ("created_at", 1)])
    db.summaries.create_index([("user_id", 1), ("kind", 1), ("created_at", -1)])
    db.episodes.create_index([("user_id", 1), ("created_at", -1)])


class MongoStore:
    def __init__(self, db=None):
        self.db = db if db is not None else doc_mongo.get_db()

    def add_message(self, user_id, session_id, role, content):
        self.db.messages.insert_one({"user_id": user_id, "session_id": session_id,
                                     "role": role, "content": content, "created_at": now()})

    def recent_messages(self, user_id, session_id, n):
        if n <= 0:
            return []
        cur = self.db.messages.find({"user_id": user_id, "session_id": session_id}) \
            .sort([("created_at", -1), ("_id", -1)]).limit(n)
        return list(reversed(list(cur)))

    def recent_user_messages(self, user_id, n):
        cur = self.db.messages.find({"user_id": user_id}) \
            .sort([("created_at", -1), ("_id", -1)]).limit(n)
        return list(reversed(list(cur)))

    def count_messages(self, user_id, session_id, role):
        return self.db.messages.count_documents(
            {"user_id": user_id, "session_id": session_id, "role": role})

    def add_summary(self, user_id, session_id, kind, content, user_msgs_covered=0):
        self.db.summaries.insert_one({"user_id": user_id, "session_id": session_id,
            "kind": kind, "content": content, "user_msgs_covered": int(user_msgs_covered),
            "created_at": now()})

    def latest_summary(self, user_id, kind, session_id=None):
        q = {"user_id": user_id, "kind": kind}
        if session_id is not None:
            q["session_id"] = session_id
        return self.db.summaries.find_one(q, sort=[("created_at", -1), ("_id", -1)])

    def recent_summaries(self, user_id, n):
        return list(self.db.summaries.find({"user_id": user_id})
                    .sort([("created_at", -1), ("_id", -1)]).limit(n))

    def add_episode(self, user_id, fact, embedding, source_session):
        self.db.episodes.insert_one({"user_id": user_id, "fact": fact, "embedding": embedding,
                                     "source_session": source_session, "created_at": now()})

    def all_episodes(self, user_id):
        return list(self.db.episodes.find({"user_id": user_id}))

    def recent_episodes(self, user_id, n):
        return list(self.db.episodes.find({"user_id": user_id}, {"embedding": 0})
                    .sort([("created_at", -1), ("_id", -1)]).limit(n))

    def daily_counts(self, user_id):
        pipe = [{"$match": {"user_id": user_id}},
                {"$group": {"_id": {"day": {"$dateToString": {"format": "%Y-%m-%d",
                                                              "date": "$created_at"}},
                                    "role": "$role"}, "n": {"$sum": 1}}},
                {"$sort": {"_id.day": 1}}]
        days = {}
        for r in self.db.messages.aggregate(pipe):
            d = days.setdefault(r["_id"]["day"], {"date": r["_id"]["day"],
                                                  "user": 0, "assistant": 0})
            d[r["_id"]["role"]] = r["n"]
        return [dict(v, total=v["user"] + v["assistant"]) for v in days.values()]

    def delete_user(self, user_id):
        for c in ("messages", "summaries", "episodes"):
            self.db[c].delete_many({"user_id": user_id})