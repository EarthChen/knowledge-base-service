"""Enhancement tests for domain overview nested navigation and entry points."""

from __future__ import annotations

from dataclasses import dataclass, field

from wiki.domain_overview_composer import DomainOverviewComposer


class TestDomainOverviewEnhancement:
    def test_nested_navigation_output(self):
        composer = DomainOverviewComposer()

        @dataclass
        class MockDomain:
            name: str
            description: str = ""
            children: list = field(default_factory=list)

        tree = [
            MockDomain(
                "Auth",
                "Authentication domain",
                [MockDomain("OAuth"), MockDomain("SAML")],
            ),
        ]
        nav = composer._build_nested_navigation(tree)
        assert "Auth" in nav
        assert "OAuth" in nav
        assert "Sub-Domains" in nav

    def test_entry_points_section(self):
        composer = DomainOverviewComposer()
        section = composer._build_entry_points_section(["UserController", "OrderController"])
        assert "UserController" in section
        assert "Entry Points" in section

    def test_empty_entry_points(self):
        composer = DomainOverviewComposer()
        section = composer._build_entry_points_section([])
        assert section == ""
