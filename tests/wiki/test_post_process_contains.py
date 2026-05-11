from indexer.post_process import match_functions_to_modules


class TestMatchFunctionsToModules:
    def test_fqn_prefix_match(self):
        modules = [
            {
                "name": "UserService",
                "fqn": "com.example.UserService",
                "file_path": "UserService.java",
                "uid": "mod-u",
            }
        ]
        functions = [
            {
                "name": "getUser",
                "fqn": "com.example.UserService.getUser",
                "file_path": "UserService.java",
                "uid": "fn-g",
            }
        ]
        result = match_functions_to_modules(modules, functions)
        assert result == [("mod-u", "fn-g")]

    def test_file_path_match(self):
        modules = [{"name": "utils", "fqn": "utils", "file_path": "src/utils.py", "uid": "mod-x"}]
        functions = [{"name": "helper", "fqn": "helper", "file_path": "src/utils.py", "uid": "fn-h"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("mod-x", "fn-h")]

    def test_no_match(self):
        modules = [{"name": "A", "fqn": "pkg.A", "file_path": "A.java", "uid": "mod-a"}]
        functions = [{"name": "orphan", "fqn": "pkg.B.orphan", "file_path": "B.java", "uid": "fn-o"}]
        result = match_functions_to_modules(modules, functions)
        assert result == []

    def test_shared_file_path_uses_last_module_uid(self):
        """Same file_path maps to one uid; last module wins for that path."""
        modules = [
            {"name": "A", "fqn": "pkg.A", "file_path": "shared.java", "uid": "mod-a"},
            {"name": "B", "fqn": "pkg.B", "file_path": "shared.java", "uid": "mod-b"},
        ]
        functions = [
            {"name": "method", "fqn": "pkg.A.method", "file_path": "shared.java", "uid": "fn-m"}
        ]
        result = match_functions_to_modules(modules, functions)
        assert result == [("mod-b", "fn-m")]

    def test_fqn_fallback_when_file_path_unknown(self):
        modules = [
            {"name": "A", "fqn": "pkg.A", "file_path": "A.java", "uid": "mod-a"},
            {"name": "B", "fqn": "pkg.B", "file_path": "B.java", "uid": "mod-b"},
        ]
        functions = [
            {"name": "method", "fqn": "pkg.A.method", "file_path": "only-fn-path.java", "uid": "fn-m"}
        ]
        result = match_functions_to_modules(modules, functions)
        assert result == [("mod-a", "fn-m")]
