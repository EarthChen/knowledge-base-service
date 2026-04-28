"""Tests for module-level docstring and file header comment extraction."""

from indexer.tree_sitter_parser import TreeSitterParser

PYTHON_MODULE_WITH_DOCSTRING = '''"""This module handles user authentication and authorization."""

import os
from typing import Optional

class AuthService:
    pass
'''

PYTHON_MODULE_NO_DOCSTRING = '''
import os

class Foo:
    pass
'''

JAVA_FILE_WITH_CLASS_DOC = '''package com.example;

import java.util.List;

/**
 * Service responsible for user authentication.
 * Handles login, logout, and session management.
 */
public class AuthService {
}
'''

JAVA_FILE_WITH_LICENSE_ONLY = '''/*
 * Copyright 2026 Company Inc.
 * Licensed under the Apache License, Version 2.0
 */
package com.example;

public class Foo {}
'''


class TestModuleDocstring:
    def test_python_module_docstring_extracted(self):
        parser = TreeSitterParser()
        result = parser.parse_file("test.py", "python", PYTHON_MODULE_WITH_DOCSTRING)
        assert "user authentication" in result.module_docstring.lower()

    def test_python_module_no_docstring(self):
        parser = TreeSitterParser()
        result = parser.parse_file("test.py", "python", PYTHON_MODULE_NO_DOCSTRING)
        assert result.module_docstring == ""

    def test_java_file_header_comment_above_class(self):
        parser = TreeSitterParser()
        result = parser.parse_file("AuthService.java", "java", JAVA_FILE_WITH_CLASS_DOC)
        assert "user authentication" in result.module_docstring.lower()

    def test_java_license_header_filtered(self):
        parser = TreeSitterParser()
        result = parser.parse_file("Foo.java", "java", JAVA_FILE_WITH_LICENSE_ONLY)
        assert result.module_docstring == ""
