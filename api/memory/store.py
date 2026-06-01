"""
IdeaMemoryStore — NDJSON-backed idea state machine.

NDJSON (Newline-Delimited JSON) means the file looks like this:
    {"idea_id": "abc", "keyword": "bamboo mug", ...}   ← line 1 = idea 1
    {"idea_id": "def", "keyword": "silicone bib", ...} ← line 2 = idea 2

Why NDJSON instead of a plain JSON array?
- Appending a new idea is a single line write, not a full file rewrite.
- Each line is independently parseable, so a corrupt line does not break the rest.
- Git diffs are human-readable — one changed line = one changed idea.
- Easy to stream for large files without loading everything into memory.

The store holds the file path and provides create / read / update / filter
methods. All writes are atomic: we write to a temp file then rename it,
so a crash mid-write can never produce a half-written file.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .schema import VALID_SOURCES, VALID_STATUSES, build_default_idea


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IdeaMemoryStore:
    """
    Manages all read/write operations against the NDJSON idea memory file.

    Usage
    -----
        store = IdeaMemoryStore("/path/to/data/ideas.ndjson")
        idea  = store.create("bamboo travel mug", source="human_seeded")
        store.update(idea["idea_id"], status="scored", tier1_score=74)
        ideas = store.filter(status="scored")
    """

    def __init__(self, file_path: str):
        """
        Parameters
        ----------
        file_path : str
            Absolute path to the NDJSON file.
            The file and its parent directory are created automatically
            if they do not already exist.
        """
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create an empty file if it does not yet exist.
        # open(..., "a").close() creates the file without truncating it.
        if not self.file_path.exists():
            self.file_path.open("a").close()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _read_all(self) -> list[dict]:
        """
        Reads every line in the NDJSON file and returns a list of idea dicts.

        Lines that are blank or cannot be parsed as JSON are silently skipped
        so a single bad line never takes the whole store down.
        """
        ideas = []
        with self.file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ideas.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip corrupt lines; in production you'd also log this.
                    pass
        return ideas

    def _write_all(self, ideas: list[dict]) -> None:
        """
        Overwrites the NDJSON file with the supplied list of ideas.

        Uses an atomic write pattern:
            1. Write to a temp file in the same directory.
            2. Rename the temp file over the real file.
        If the process is killed between steps 1 and 2, the original file
        is untouched. The OS rename is atomic on both Linux and Windows.
        """
        dir_ = self.file_path.parent
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for idea in ideas:
                    f.write(json.dumps(idea, ensure_ascii=False) + "\n")
            # Atomic rename: replaces the destination if it exists.
            os.replace(tmp_path, self.file_path)
        except Exception:
            # Clean up the temp file if anything goes wrong.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── Create ────────────────────────────────────────────────────────────────

    def create(
        self,
        keyword: str,
        concept: str = "",
        source: str = "human_seeded",
        allow_duplicate: bool = False,
    ) -> dict:
        """
        Creates a new idea record and appends it to the NDJSON file.

        Parameters
        ----------
        keyword : str
            The Amazon search keyword. Will be lowercased and stripped.

        concept : str
            Optional human description of the product concept.

        source : str
            "human_seeded" | "autonomous" | "adjacency_mining"

        allow_duplicate : bool
            If False (default), raises ValueError when an idea with the same
            keyword already exists in a non-dismissed status.
            Set to True to force a fresh evaluation of the same keyword.

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

        # Append a single line — more efficient than reading+rewriting the whole file.
        with self.file_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(idea, ensure_ascii=False) + "\n")

        return idea

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, idea_id: str) -> Optional[dict]:
        """
        Returns the idea with the given idea_id, or None if not found.
        """
        for idea in self._read_all():
            if idea.get("idea_id") == idea_id:
                return idea
        return None

    def get_by_keyword(self, keyword: str) -> Optional[dict]:
        """
        Returns the most recently created idea that matches the keyword.
        Keyword matching is case-insensitive.

        Returns None if no match is found.
        """
        keyword = keyword.strip().lower()
        matches = [i for i in self._read_all() if i.get("keyword") == keyword]
        if not matches:
            return None
        # Most recently created = last in the file (we always append).
        return matches[-1]

    def list_all(self) -> list[dict]:
        """
        Returns all idea records as a list.
        """
        return self._read_all()

    def count(self) -> int:
        """
        Returns the total number of idea records in the store.
        """
        return len(self._read_all())

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
    ) -> list[dict]:
        """
        Returns ideas that match ALL supplied criteria.

        Any parameter left as None is not used as a filter.

        Parameters
        ----------
        status : str
            e.g. "scored", "shortlisted"

        source : str
            e.g. "human_seeded", "autonomous"

        tier1_done : bool
            True → only ideas that have completed Tier 1 scoring.
            False → only ideas waiting for Tier 1 scoring.

        reviews_scraped : bool
            Filter by whether review scraping has completed.

        research_done : bool
            Filter by whether AI deep research has completed.

        presourcing_done : bool
            Filter by whether pre-sourcing generation has completed.

        has_flag : str
            Returns only ideas whose flags list contains this exact string.
            e.g. has_flag="hard_kill"

        min_tier1_score : float
            Returns only ideas whose tier1_score >= this value.

        Returns
        -------
        list[dict]
            List of matching idea records, in creation order.
        """
        results = self._read_all()

        if status is not None:
            results = [i for i in results if i.get("status") == status]

        if source is not None:
            results = [i for i in results if i.get("source") == source]

        if tier1_done is not None:
            results = [i for i in results if i.get("tier1_done") == tier1_done]

        if reviews_scraped is not None:
            results = [i for i in results if i.get("reviews_scraped") == reviews_scraped]

        if research_done is not None:
            results = [i for i in results if i.get("research_done") == research_done]

        if presourcing_done is not None:
            results = [i for i in results if i.get("presourcing_done") == presourcing_done]

        if has_flag is not None:
            results = [i for i in results if has_flag in i.get("flags", [])]

        if min_tier1_score is not None:
            results = [
                i for i in results
                if i.get("tier1_score") is not None and i["tier1_score"] >= min_tier1_score
            ]

        return results

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, idea_id: str, **fields) -> dict:
        """
        Updates fields on an existing idea record.

        How it works
        ------------
        1. Read every line into memory.
        2. Find the idea with the matching idea_id.
        3. Deep-merge the supplied fields into the existing record.
        4. Stamp updated_at with the current time.
        5. Write all records back to the file (atomic temp-file rename).

        Parameters
        ----------
        idea_id : str
            The unique ID of the idea to update.

        **fields : any
            Any top-level field(s) from the idea schema, e.g.:
                store.update(idea_id, status="scored", tier1_score=74)
                store.update(idea_id, flags=["low_demand"])
                store.update(idea_id, tier1_done=True, tier1_at="2026-06-01T10:00:00+00:00")

        Returns
        -------
        dict
            The fully updated idea record.

        Raises
        ------
        KeyError
            If no idea with the given idea_id exists.
        ValueError
            If a supplied field value fails validation (e.g. bad status string).
        """
        # Validate status if it is being changed
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{fields['status']}'. Must be one of {VALID_STATUSES}"
            )

        ideas = self._read_all()
        target_index = None

        for i, idea in enumerate(ideas):
            if idea.get("idea_id") == idea_id:
                target_index = i
                break

        if target_index is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")

        # Merge supplied fields into the existing record.
        # For dict fields (tier1_scores, tier1_evidence, etc.) we do a shallow
        # merge so the caller can update one sub-key without wiping the rest.
        existing = ideas[target_index]
        for key, value in fields.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key] = {**existing[key], **value}
            else:
                existing[key] = value

        existing["updated_at"] = _now_iso()
        ideas[target_index] = existing
        self._write_all(ideas)
        return existing

    # ── Flag helpers ──────────────────────────────────────────────────────────

    def add_flag(self, idea_id: str, flag: str) -> dict:
        """
        Adds a flag string to the idea's flags list (no duplicates).

        Example
        -------
            store.add_flag(idea_id, "hard_kill")
            store.add_flag(idea_id, "no_ba_data")
        """
        idea = self.get(idea_id)
        if idea is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")

        flags = idea.get("flags", [])
        if flag not in flags:
            flags.append(flag)
        return self.update(idea_id, flags=flags)

    def remove_flag(self, idea_id: str, flag: str) -> dict:
        """
        Removes a flag string from the idea's flags list.
        Does nothing if the flag is not present.
        """
        idea = self.get(idea_id)
        if idea is None:
            raise KeyError(f"No idea found with idea_id='{idea_id}'")

        flags = [f for f in idea.get("flags", []) if f != flag]
        return self.update(idea_id, flags=flags)

    # ── Cooldown helpers ──────────────────────────────────────────────────────

    def set_cooldown(self, idea_id: str, hours: int) -> dict:
        """
        Sets a cooldown on the idea so the scorer skips it for `hours` hours.

        The scorer should call is_on_cooldown() before processing an idea.

        Example
        -------
            # Re-evaluate this idea in 48 hours
            store.set_cooldown(idea_id, hours=48)
        """
        until = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
        return self.update(idea_id, cooldown_until=until)

    def is_on_cooldown(self, idea_id: str) -> bool:
        """
        Returns True if the idea is still within its cooldown window.

        The scorer calls this before spending scrape credits on an idea.

        Example
        -------
            if store.is_on_cooldown(idea_id):
                continue  # skip this idea, check again later
        """
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
        """
        Convenience wrapper to update just the status field.

        Example
        -------
            store.set_status(idea_id, "scored")
        """
        return self.update(idea_id, status=new_status)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, idea_id: str) -> bool:
        """
        Permanently removes an idea from the store.

        Returns True if the idea was found and deleted, False if not found.

        Use with caution — prefer set_status("dismissed") to keep an audit trail.
        """
        ideas = self._read_all()
        filtered = [i for i in ideas if i.get("idea_id") != idea_id]

        if len(filtered) == len(ideas):
            return False  # Nothing was removed

        self._write_all(filtered)
        return True

    # ── Exists ────────────────────────────────────────────────────────────────

    def exists(self, keyword: str) -> bool:
        """
        Returns True if any non-dismissed idea already exists for this keyword.

        The scorer calls this before creating a duplicate entry.
        """
        idea = self.get_by_keyword(keyword)
        return idea is not None and idea.get("status") != "dismissed"
