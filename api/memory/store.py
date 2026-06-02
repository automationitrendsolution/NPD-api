"""
IdeaMemoryStore — MongoDB-backed idea state machine.

Replaces the NDJSON file store. Each idea is a document in the 'ideas'
MongoDB collection with idea_id as a unique index for O(1) lookups.

The constructor still accepts a file_path argument for backward compatibility
with existing callers (settings.IDEA_MEMORY_PATH) but ignores it.
The MongoDB connection is always established via the MONGO_URI env variable.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pymongo import MongoClient, DESCENDING

from .schema import VALID_SOURCES, VALID_STATUSES, build_default_idea


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("#")[0] if '"' not in value and "'" not in value else value
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Module-level client — MongoClient is thread-safe and manages its own pool.
_mongo_client: Optional[MongoClient] = None


def _get_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/npd_db")
        _mongo_client = MongoClient(uri)
    return _mongo_client


def _get_collection():
    db_name = os.getenv("MONGO_DB", "npd_db")
    return _get_client()[db_name]["ideas"]


class IdeaMemoryStore:
    """
    Manages all read/write operations against the MongoDB 'ideas' collection.

    Usage
    -----
        store = IdeaMemoryStore(settings.IDEA_MEMORY_PATH)  # path argument ignored
        idea  = store.create("bamboo travel mug", source="human_seeded")
        store.update(idea["idea_id"], status="scored", tier1_score=74)
        ideas = store.filter(status="scored")
    """

    def __init__(self, file_path=None):
        self._col = _get_collection()
        # Unique index on idea_id ensures fast lookups and prevents duplicates.
        self._col.create_index("idea_id", unique=True)

    # ── Create ────────────────────────────────────────────────────────────────

    def create(
        self,
        keyword: str,
        concept: str = "",
        source: str = "human_seeded",
        allow_duplicate: bool = False,
    ) -> dict:
        """
        Creates a new idea document and inserts it into MongoDB.

        Parameters
        ----------
        keyword : str
            The Amazon search keyword. Lowercased and stripped before storage.
        concept : str
            Optional human description of the product concept.
        source : str
            "human_seeded" | "autonomous" | "adjacency_mining"
        allow_duplicate : bool
            If False (default), raises ValueError when an idea with the same
            keyword already exists in a non-dismissed status.

        Returns
        -------
        dict
            The newly created idea record.
        """
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source '{source}'. Must be one of {VALID_SOURCES}")

        normalised_keyword = keyword.strip().lower()

        if not allow_duplicate:
            existing = self.get_by_keyword(normalised_keyword)
            if existing and existing["status"] != "dismissed":
                raise ValueError(
                    f"Idea for keyword '{normalised_keyword}' already exists "
                    f"(idea_id={existing['idea_id']}, status={existing['status']}). "
                    f"Pass allow_duplicate=True to create a second record."
                )

        idea = build_default_idea(normalised_keyword, concept, source)
        self._col.insert_one({**idea})
        return idea

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, idea_id: str) -> Optional[dict]:
        """Returns the idea with the given idea_id, or None if not found."""
        return self._col.find_one({"idea_id": idea_id}, {"_id": 0})

    def get_by_keyword(self, keyword: str) -> Optional[dict]:
        """
        Returns the most recently inserted idea that matches the keyword.
        Keyword matching is case-insensitive.
        """
        keyword = keyword.strip().lower()
        return self._col.find_one(
            {"keyword": keyword},
            {"_id": 0},
            sort=[("_id", DESCENDING)],
        )

    def list_all(self) -> list:
        """Returns all idea records as a list."""
        return list(self._col.find({}, {"_id": 0}))

    def count(self) -> int:
        """Returns the total number of idea records in the store."""
        return self._col.count_documents({})

    # ── Filter ────────────────────────────────────────────────────────────────

    def filter(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        tier1_done: Optional[bool] = None,
        reviews_scraped: Optional[bool] = None,
        research_done: Optional[bool] = None,
        presourcing_done: Optional[bool] = None,
        has_flag: Optional[str] = None,
        min_tier1_score: Optional[float] = None,
    ) -> list:
        """
        Returns ideas that match ALL supplied criteria (AND logic).
        Any parameter left as None is not applied as a filter.
        """
        query = {}
        if status is not None:
            query["status"] = status
        if source is not None:
            query["source"] = source
        if tier1_done is not None:
            query["tier1_done"] = tier1_done
        if reviews_scraped is not None:
            query["reviews_scraped"] = reviews_scraped
        if research_done is not None:
            query["research_done"] = research_done
        if presourcing_done is not None:
            query["presourcing_done"] = presourcing_done
        if has_flag is not None:
            query["flags"] = has_flag
        if min_tier1_score is not None:
            query["tier1_score"] = {"$gte": min_tier1_score}

        return list(self._col.find(query, {"_id": 0}))

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, idea_id: str, **fields) -> dict:
        """
        Updates fields on an existing idea document.

        Performs a shallow merge for dict fields so a caller can update one
        sub-key (e.g. tier1_scores.demand) without wiping the rest.

        Parameters
        ----------
        idea_id : str
            The unique ID of the idea to update.
        **fields : any
            Any top-level field(s) from the idea schema.

        Returns
        -------
        dict
            The fully updated idea record.

        Raises
        ------
        KeyError
            If no idea with the given idea_id exists.
        ValueError
            If a supplied status value is not in VALID_STATUSES.
        """
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{fields['status']}'. Must be one of {VALID_STATUSES}"
            )

        existing = self.get(idea_id)
        if existing is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")

        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key] = {**existing[key], **value}
            else:
                existing[key] = value

        existing["updated_at"] = _now_iso()
        self._col.update_one({"idea_id": idea_id}, {"$set": existing})
        return existing

    # ── Flag helpers ──────────────────────────────────────────────────────────

    def add_flag(self, idea_id: str, flag: str) -> dict:
        """Adds a flag string to the idea's flags list (no duplicates)."""
        idea = self.get(idea_id)
        if idea is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")
        flags = idea.get("flags", [])
        if flag not in flags:
            flags.append(flag)
        return self.update(idea_id, flags=flags)

    def remove_flag(self, idea_id: str, flag: str) -> dict:
        """Removes a flag string from the idea's flags list."""
        idea = self.get(idea_id)
        if idea is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")
        flags = [f for f in idea.get("flags", []) if f != flag]
        return self.update(idea_id, flags=flags)

    # ── Cooldown helpers ──────────────────────────────────────────────────────

    def set_cooldown(self, idea_id: str, hours: int) -> dict:
        """Sets a cooldown so the scorer skips this idea for `hours` hours."""
        until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        return self.update(idea_id, cooldown_until=until)

    def is_on_cooldown(self, idea_id: str) -> bool:
        """Returns True if the idea is still within its cooldown window."""
        idea = self.get(idea_id)
        if idea is None:
            return False
        cooldown_until = idea.get("cooldown_until")
        if not cooldown_until:
            return False
        try:
            until_dt = datetime.fromisoformat(cooldown_until)
            return datetime.now(timezone.utc) < until_dt
        except ValueError:
            return False

    # ── Status transition helpers ─────────────────────────────────────────────

    def set_status(self, idea_id: str, new_status: str) -> dict:
        """Convenience wrapper to update just the status field."""
        return self.update(idea_id, status=new_status)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, idea_id: str) -> bool:
        """
        Permanently removes an idea from the store.
        Returns True if found and deleted, False if not found.
        Prefer set_status("dismissed") to keep an audit trail.
        """
        result = self._col.delete_one({"idea_id": idea_id})
        return result.deleted_count > 0

    # ── Exists ────────────────────────────────────────────────────────────────

    def exists(self, keyword: str) -> bool:
        """Returns True if any non-dismissed idea exists for this keyword."""
        idea = self.get_by_keyword(keyword)
        return idea is not None and idea.get("status") != "dismissed"
