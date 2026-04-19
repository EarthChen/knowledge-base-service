"""Tests for ImportResolver — import path → indexed file path."""

from __future__ import annotations

from indexer.import_resolver import ImportResolver


def test_resolve_python_import() -> None:
    """from foo.bar import Baz → foo/bar.py 或 foo/bar/__init__.py."""
    paths = ["foo/bar.py", "pkg/spam/__init__.py"]
    fi = ImportResolver.build_file_index(paths)
    r = ImportResolver(fi)

    assert r.resolve("foo.bar", "main.py", "python") == "foo/bar.py"
    assert r.resolve("pkg.spam", "main.py", "python") == "pkg/spam/__init__.py"


def test_resolve_python_relative_import() -> None:
    """from .models import User → 当前包下的 models.py。"""
    paths = ["app/pkg/models.py", "app/pkg/runner.py"]
    fi = ImportResolver.build_file_index(paths)
    r = ImportResolver(fi)

    assert r.resolve(".models", "app/pkg/runner.py", "python") == "app/pkg/models.py"


def test_resolve_js_import() -> None:
    """import { X } from './utils/helper' → utils/helper.ts|.js|/index.ts。"""
    paths = [
        "src/utils/helper.ts",
        "src/utils/alias.js",
        "components/ui/index.tsx",
        "lib/mod/index.js",
    ]
    fi = ImportResolver.build_file_index(paths)
    r = ImportResolver(fi)

    assert r.resolve("./utils/helper", "src/app.tsx", "typescript") == "src/utils/helper.ts"
    assert (
        r.resolve("./utils/alias", "src/app.tsx", "javascript") == "src/utils/alias.js"
    )
    assert (
        r.resolve("./ui", "components/main.tsx", "typescript") == "components/ui/index.tsx"
    )
    assert r.resolve("../lib/mod", "components/main.tsx", "typescript") == "lib/mod/index.js"


def test_resolve_java_import() -> None:
    """import com.example.service.UserService → com/example/service/UserService.java。"""
    paths = ["src/main/java/com/example/service/UserService.java"]
    fi = ImportResolver.build_file_index(paths)
    r = ImportResolver(fi)

    assert (
        r.resolve("com.example.service.UserService", "com/example/App.java", "java")
        == "src/main/java/com/example/service/UserService.java"
    )


def test_resolve_go_import() -> None:
    """import "github.com/example/pkg/utils" → 包目录下的某一 .go 文件。"""
    paths = [
        "vendor/github.com/example/pkg/utils/foo.go",
        "vendor/github.com/example/pkg/utils/bar.go",
    ]
    fi = ImportResolver.build_file_index(paths)
    r = ImportResolver(fi)

    out = r.resolve("github.com/example/pkg/utils", "cmd/main.go", "go")
    assert out in paths


def test_no_match_returns_none() -> None:
    fi = ImportResolver.build_file_index(["a/b.py"])
    r = ImportResolver(fi)

    assert r.resolve("missing.module", "x.py", "python") is None
    assert r.resolve("./nowhere", "src/a.ts", "typescript") is None


def test_build_import_index() -> None:
    """给定文件列表，构建 module → file 列表的映射。"""
    paths = ["foo/bar.py", "foo/baz.py", "foo/__init__.py"]
    idx = ImportResolver.build_module_index(paths)

    assert "foo.bar" in idx
    assert set(idx["foo.bar"]) == {"foo/bar.py"}
    assert "foo" in idx
    assert set(idx["foo"]) == {"foo/__init__.py"}
    assert set(idx["foo.baz"]) == {"foo/baz.py"}
