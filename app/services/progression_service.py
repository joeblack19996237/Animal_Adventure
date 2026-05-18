from __future__ import annotations

import json
import logging
from pathlib import Path

from app.db import connect_db

logger = logging.getLogger(__name__)


class ProgressionService:
    def __init__(self, db_path: Path, config_dir: Path) -> None:
        self._db_path = db_path
        self._level_rules = self._load_progression(config_dir)

    def _load_progression(self, config_dir: Path) -> dict[int, dict]:
        data: dict = json.loads(
            (config_dir / "progression.json").read_text(encoding="utf-8")
        )
        return {int(k): v for k, v in data.get("levels", {}).items()}

    def check_and_apply_progression(self, player_id: str) -> dict:
        conn = connect_db(self._db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            player_row = conn.execute(
                "SELECT level FROM players WHERE id=?", (player_id,)
            ).fetchone()
            if player_row is None:
                conn.execute("ROLLBACK")
                return {"type": "no_change"}

            current_level = int(player_row[0])
            prog_row = conn.execute(
                "SELECT unique_completed_quest_ids_json, used_potion_count, unlocked_regions_json "
                "FROM player_progress WHERE player_id=?",
                (player_id,),
            ).fetchone()
            if prog_row is None:
                conn.execute("ROLLBACK")
                return {"type": "no_change"}

            unique_quest_ids: list[str] = json.loads(prog_row[0])
            used_potion_count: int = int(prog_row[1])
            unlocked_regions: list[str] = json.loads(prog_row[2])

            for target_level, rule in sorted(self._level_rules.items()):
                if current_level >= target_level:
                    continue
                required_quests = int(rule.get("unique_completed_quest_ids", 0))
                required_potions = int(rule.get("used_potion_count", 0))
                if (
                    len(unique_quest_ids) >= required_quests
                    and used_potion_count >= required_potions
                ):
                    for region in rule.get("unlock_regions", []):
                        if region not in unlocked_regions:
                            unlocked_regions.append(region)
                    conn.execute(
                        "UPDATE players SET level=? WHERE id=?",
                        (target_level, player_id),
                    )
                    conn.execute(
                        "UPDATE player_progress SET unlocked_level=?, unlocked_regions_json=? WHERE player_id=?",
                        (target_level, json.dumps(unlocked_regions), player_id),
                    )
                    conn.execute("COMMIT")
                    logger.info(
                        "Level up player=%s new_level=%d regions=%s",
                        player_id,
                        target_level,
                        unlocked_regions,
                    )
                    return {
                        "type": "level_up",
                        "level": target_level,
                        "unlocked_regions": unlocked_regions,
                    }

            conn.execute("ROLLBACK")
            return {"type": "no_change"}
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
