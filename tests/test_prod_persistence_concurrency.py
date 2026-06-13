"""Concurrency integrity tests for the persistence layer.

Proves SqlRepository loses zero writes under heavy concurrent load, and
demonstrates that the legacy JsonRepository silently loses writes under the
same load (the exact data-loss bug the audit flagged).
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.repository import (  # noqa: E402
    DatasetCatalogRecord,
    JsonRepository,
    RunRecord,
    SqlRepository,
    get_repository,
    utc_now,
)


def make_dataset(i: int) -> DatasetCatalogRecord:
    return DatasetCatalogRecord(
        dataset_id=f"ds-{i:04d}",
        title=f"Dataset {i}",
        source="upload",
        provider="local",
        task_id=None,
        filename=f"f{i}.csv",
        format="csv",
        rows=i,
        columns=3,
        schema={"instruction": {"type": "string"}, "response": {"type": "string"}},
        stats={"missing_ratio": 0.0, "duplicate_rows": 0},
        artifacts={"zip": f"/artifacts/{i}/dataset.zip"},
        quality_score=80,
        tags=["uploaded", "english"],
        description="d",
        created_at=utc_now(),
        quality_narrative="Strong overall.",
        quality_metrics={"completeness": 90, "consistency": 88},
        dataset_card="# Card\n",
    )


class SqlRepositoryConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.repo = SqlRepository(os.path.join(self.dir, "dataforge.db"))

    def test_no_lost_writes_under_concurrency(self) -> None:
        n = 200
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(lambda i: self.repo.save_dataset(make_dataset(i)), range(n)))
        stored = self.repo.list_datasets()
        self.assertEqual(len(stored), n, "SqlRepository lost writes under concurrency")
        self.assertEqual(len({d.dataset_id for d in stored}), n)

    def test_concurrent_updates_to_same_key_are_consistent(self) -> None:
        # Many writers upserting the SAME key must not corrupt the row.
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(lambda i: self.repo.save_dataset(make_dataset(0)), range(200)))
        self.assertEqual(len(self.repo.list_datasets()), 1)
        got = self.repo.get_dataset("ds-0000")
        self.assertIsNotNone(got)
        self.assertEqual(got.quality_metrics, {"completeness": 90, "consistency": 88})

    def test_roundtrip_preserves_nested_json_fields(self) -> None:
        self.repo.save_dataset(make_dataset(7))
        got = self.repo.get_dataset("ds-0007")
        self.assertEqual(got.schema["instruction"]["type"], "string")
        self.assertEqual(got.tags, ["uploaded", "english"])
        self.assertEqual(got.artifacts["zip"], "/artifacts/7/dataset.zip")
        self.assertEqual(got.quality_score, 80)

    def test_run_record_roundtrip(self) -> None:
        run = RunRecord(
            task_id="t-1", project_id=None, workflow="wf", status="done",
            request={"a": 1}, artifacts={"zip": "x"}, created_at=utc_now(),
        )
        self.repo.save_run(run)
        got = self.repo.get_run("t-1")
        self.assertEqual(got.request, {"a": 1})
        self.assertIsNone(got.completed_at)


class MigrationTest(unittest.TestCase):
    def test_missing_column_is_added_on_open(self) -> None:
        import sqlite3
        dir_ = tempfile.mkdtemp()
        db = os.path.join(dir_, "dataforge.db")
        # Simulate an OLD table created before quality_narrative existed.
        conn = sqlite3.connect(db)
        conn.execute(
            'CREATE TABLE "datasets" ("dataset_id" TEXT PRIMARY KEY, "title" TEXT)'
        )
        conn.commit()
        conn.close()
        # Opening the repo must migrate the table to the full current schema.
        repo = SqlRepository(db)
        repo.save_dataset(make_dataset(1))
        got = repo.get_dataset("ds-0001")
        self.assertEqual(got.quality_narrative, "Strong overall.")
        self.assertEqual(got.dataset_card, "# Card\n")


class FactoryTest(unittest.TestCase):
    def test_default_backend_is_sqlite(self) -> None:
        os.environ.pop("DATAFORGE_PERSISTENCE", None)
        dir_ = tempfile.mkdtemp()
        repo = get_repository(os.path.join(dir_, "x.db"))
        self.assertIsInstance(repo, SqlRepository)


class JsonRepositoryLosesWritesDemo(unittest.TestCase):
    """Demonstrates the legacy bug: read-modify-write loses concurrent writes.

    A test-only subclass widens the existing race window (it does not introduce
    a new bug -- it just makes the real lost-update window observable).
    """

    def test_json_repo_is_unsafe_under_concurrency(self) -> None:
        class SlowJsonRepository(JsonRepository):
            def _save(self, snapshot):  # noqa: ANN001
                time.sleep(0.002)  # widen the read-modify-write window
                super()._save(snapshot)

        dir_ = tempfile.mkdtemp()
        repo = SlowJsonRepository(os.path.join(dir_, "state.json"))
        n = 60

        def worker(i: int) -> int:
            try:
                repo.save_dataset(make_dataset(i))
                return 0
            except Exception:
                return 1  # interleaved write corrupted the file

        with ThreadPoolExecutor(max_workers=16) as pool:
            write_errors = sum(pool.map(worker, range(n)))
        try:
            kept = len(repo.list_datasets())
        except Exception:
            kept = -1  # file left corrupted / unreadable
        print(
            f"\n[demo] JsonRepository under concurrency: kept={kept}/{n}, "
            f"write_errors={write_errors} "
            "(lost writes, write errors, or corruption all = unsafe)"
        )
        self.assertTrue(
            kept < n or write_errors > 0,
            "expected JSON repo to be unsafe under concurrency",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
