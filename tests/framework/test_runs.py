"""Unit tests for the run-layout module: slugs, numbered run-dir allocation, and the project store."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.shared.core.runs import slugify, allocate_run_dir, Project, Projects


class SlugifyTests(unittest.TestCase):
    def test_human_friendly_lowercase_collapsed(self) -> None:
        self.assertEqual(slugify("CLI: JSON → CSV converter!"), "cli-json-csv-converter")

    def test_cap_and_trim(self) -> None:
        s = slugify("x" * 100, max_len=10)
        self.assertLessEqual(len(s), 10)
        self.assertFalse(s.endswith("-"))

    def test_empty_falls_back(self) -> None:
        self.assertEqual(slugify("!!!"), "run")
        self.assertEqual(slugify(""), "run")


class AllocateRunDirTests(unittest.TestCase):
    def test_numbering_increments_and_label_preserves_case(self) -> None:
        with TemporaryDirectory() as td:
            pdir = Path(td) / "proj"
            r1 = allocate_run_dir(pdir, "nexus", "plan")
            r1.mkdir(parents=True)
            r2 = allocate_run_dir(pdir, "exec", "TASK-01")
            self.assertTrue(r1.name.startswith("001_nexus_plan_"))
            self.assertTrue(r2.name.startswith("002_exec_TASK-01_"))  # case preserved, number advances

    def test_unique_within_same_label(self) -> None:
        with TemporaryDirectory() as td:
            pdir = Path(td) / "proj"
            a = allocate_run_dir(pdir, "exec", "TASK-01"); a.mkdir(parents=True)
            b = allocate_run_dir(pdir, "exec", "TASK-01"); b.mkdir(parents=True)
            self.assertNotEqual(a.name, b.name)              # uid suffix → no overwrite


class ProjectsStoreTests(unittest.TestCase):
    def test_create_persists_and_loads(self) -> None:
        with TemporaryDirectory() as td:
            store = Projects(Path(td))
            p = store.create("My Idea", idea="My Idea", repo="git@h:r.git", base_branch="dev")
            self.assertEqual(p.slug, "my-idea")
            self.assertTrue((Path(td) / "my-idea" / "project.json").is_file())
            loaded = store.load("my-idea")
            self.assertEqual((loaded.repo, loaded.base_branch, loaded.idea), ("git@h:r.git", "dev", "My Idea"))

    def test_create_suffixes_on_collision(self) -> None:
        with TemporaryDirectory() as td:
            store = Projects(Path(td))
            a = store.create("dup")
            b = store.create("dup")
            self.assertEqual((a.slug, b.slug), ("dup", "dup-2"))

    def test_get_or_create_reuses_and_captures_repo(self) -> None:
        with TemporaryDirectory() as td:
            store = Projects(Path(td))
            store.create("DEMO-1")                            # no repo yet
            again = store.get_or_create("DEMO-1", repo="git@h:r.git")
            self.assertEqual(again.slug, "demo-1")            # reused, not suffixed
            self.assertEqual(store.load("demo-1").repo, "git@h:r.git")  # repo captured

    def test_latest_run_and_run_by_number(self) -> None:
        with TemporaryDirectory() as td:
            store = Projects(Path(td))
            store.create("p")
            store.allocate("p", "nexus", "plan").mkdir(parents=True)   # 001
            ex = store.allocate("p", "exec", "TASK-01"); ex.mkdir(parents=True)  # 002
            self.assertEqual(store.run_by_number("p", 2), ex)
            self.assertEqual(store.run_by_number("p", "002"), ex)
            self.assertTrue(store.latest_run("p", plane="nexus").name.startswith("001_nexus_"))
            self.assertEqual(store.latest_run("p"), ex)        # newest overall


if __name__ == "__main__":
    unittest.main()
