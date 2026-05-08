from indexer.post_process import match_functions_to_modules


class TestMatchFunctionsToModules:
    def test_fqn_prefix_match(self):
        modules = [{"name": "UserService", "fqn": "com.example.UserService", "file_path": "UserService.java"}]
        functions = [{"name": "getUser", "fqn": "com.example.UserService.getUser", "file_path": "UserService.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("UserService", "getUser")]

    def test_file_path_match(self):
        modules = [{"name": "utils", "fqn": "utils", "file_path": "src/utils.py"}]
        functions = [{"name": "helper", "fqn": "helper", "file_path": "src/utils.py"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("utils", "helper")]

    def test_no_match(self):
        modules = [{"name": "A", "fqn": "pkg.A", "file_path": "A.java"}]
        functions = [{"name": "orphan", "fqn": "pkg.B.orphan", "file_path": "B.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == []

    def test_fqn_takes_priority_over_filepath(self):
        modules = [
            {"name": "A", "fqn": "pkg.A", "file_path": "shared.java"},
            {"name": "B", "fqn": "pkg.B", "file_path": "shared.java"},
        ]
        functions = [{"name": "method", "fqn": "pkg.A.method", "file_path": "shared.java"}]
        result = match_functions_to_modules(modules, functions)
        assert result == [("A", "method")]
