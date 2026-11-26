"""Tests for ui/router.py — URL routing (ui_redesign.md §4.3 P1-1)."""

from __future__ import annotations

import param
import pytest

from pynpxpipe.ui.router import Router, build_query, parse_query


class FakeLocation(param.Parameterized):
    search = param.String(default="")


class TestQuery:
    def test_parse_known_keys(self):
        assert parse_query("?view=session&dir=D%3A%2Fout%2Fx&stage=sort") == {
            "view": "session",
            "output_dir": "D:/out/x",
            "stage": "sort",
        }

    def test_unknown_view_falls_back_to_sessions(self):
        assert parse_query("?view=nope")["view"] == "sessions"
        assert parse_query("")["view"] == "sessions"

    def test_build_omits_empty_values(self):
        assert build_query("new", "", "") == "?view=new"
        assert parse_query(build_query("session", "D:/out/a b", "sort")) == {
            "view": "session",
            "output_dir": "D:/out/a b",
            "stage": "sort",
        }


class TestRouter:
    def test_defaults_without_location(self):
        router = Router()
        assert (router.view, router.output_dir, router.stage) == ("sessions", "", "")

    def test_initial_state_comes_from_location(self):
        loc = FakeLocation(search="?view=session&dir=D%3A%2Fout")
        router = Router(loc)
        assert (router.view, router.output_dir) == ("session", "D:/out")

    def test_go_updates_params_and_location(self):
        loc = FakeLocation()
        router = Router(loc)
        router.go("session", output_dir="D:/out", stage="sort")
        assert (router.view, router.output_dir, router.stage) == ("session", "D:/out", "sort")
        assert parse_query(loc.search) == {
            "view": "session",
            "output_dir": "D:/out",
            "stage": "sort",
        }

    def test_go_to_view_without_dir_clears_session_params(self):
        router = Router(FakeLocation())
        router.go("session", output_dir="D:/out", stage="sort")
        router.go("new")
        assert (router.view, router.output_dir, router.stage) == ("new", "", "")

    def test_browser_navigation_updates_router(self):
        loc = FakeLocation()
        router = Router(loc)
        loc.search = "?view=help"
        assert router.view == "help"

    def test_rejects_unknown_view(self):
        with pytest.raises(ValueError):
            Router().go("bogus")
