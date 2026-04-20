"""Tests for annotation semantic mapping and classification."""

import pytest

from indexer.annotation_semantics import SemanticRole, classify_annotations, lookup_annotation


class TestLookupAnnotation:
    def test_lookup_simple_annotation(self):
        sem = lookup_annotation("@Service")
        assert sem is not None
        assert sem.role == SemanticRole.SERVICE
        assert sem.framework == "spring"

    def test_lookup_moa_provider(self):
        sem = lookup_annotation("@MoaProvider")
        assert sem is not None
        assert sem.role == SemanticRole.RPC_PROVIDER
        assert sem.framework == "moa"

    def test_lookup_moa_consumer(self):
        sem = lookup_annotation("@MoaConsumer")
        assert sem is not None
        assert sem.role == SemanticRole.RPC_CONSUMER
        assert sem.framework == "moa"
        assert sem.target == "field"

    def test_lookup_dubbo_service(self):
        sem = lookup_annotation("@DubboService")
        assert sem is not None
        assert sem.role == SemanticRole.RPC_PROVIDER
        assert sem.framework == "dubbo"

    def test_lookup_dubbo_reference(self):
        sem = lookup_annotation("@DubboReference")
        assert sem is not None
        assert sem.role == SemanticRole.RPC_CONSUMER
        assert sem.framework == "dubbo"

    def test_lookup_with_arguments(self):
        sem = lookup_annotation('@RequestMapping("/api/users")')
        assert sem is not None
        assert sem.role == SemanticRole.HTTP_ENDPOINT

    def test_lookup_java_fqn(self):
        sem = lookup_annotation("@org.springframework.stereotype.Service")
        assert sem is not None
        assert sem.role == SemanticRole.SERVICE

    def test_lookup_unknown_annotation(self):
        assert lookup_annotation("@CustomAnnotation") is None

    def test_lookup_empty_string(self):
        assert lookup_annotation("") is None

    def test_lookup_python_decorator(self):
        sem = lookup_annotation("@app.route")
        assert sem is not None
        assert sem.role == SemanticRole.HTTP_ENDPOINT

    def test_lookup_router_pattern(self):
        sem = lookup_annotation("@router.get")
        assert sem is not None
        assert sem.role == SemanticRole.HTTP_ENDPOINT

    def test_lookup_mybatis_plus_table_name(self):
        sem = lookup_annotation('@TableName("t_user")')
        assert sem is not None
        assert sem.role == SemanticRole.ENTITY
        assert sem.framework == "mybatis-plus"
        assert sem.target == "class"

    def test_lookup_table_name_fqn(self):
        sem = lookup_annotation("@com.baomidou.mybatisplus.annotation.TableName")
        assert sem is not None
        assert sem.role == SemanticRole.ENTITY


class TestClassifyAnnotations:
    def test_classify_annotations_multiple(self):
        assert classify_annotations(["@Service", "@Transactional"]) == ["service", "transaction"]

    def test_classify_annotations_dedup(self):
        assert classify_annotations(["@GetMapping", "@PostMapping"]) == ["http_endpoint"]

    def test_classify_annotations_empty(self):
        assert classify_annotations([]) == []
