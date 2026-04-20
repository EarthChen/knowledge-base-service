"""Tests for Moa RPC annotation parsing and Immomo Kafka inheritance heuristics."""

from indexer.graph_enricher import (
    _extract_kafka_listener_topics_from_java_text,
    _java_extends_company_kafka_listener,
)
from indexer.java_annotation_args import extract_java_annotation_primary_arg


class TestExtractJavaAnnotationPrimaryArg:
    def test_interface_class_spaced(self) -> None:
        ann = "@MoaConsumer(interfaceClass = SomeService.class)"
        assert extract_java_annotation_primary_arg(ann) == "SomeService"

    def test_interface_class_fqn(self) -> None:
        ann = "@MoaConsumer(interfaceClass=com.foo.SomeService.class)"
        assert extract_java_annotation_primary_arg(ann) == "SomeService"

    def test_moa_provider_interface_class(self) -> None:
        ann = "@MoaProvider(interfaceClass = com.bar.OtherApi.class)"
        assert extract_java_annotation_primary_arg(ann) == "OtherApi"

    def test_http_mapping_unchanged(self) -> None:
        assert extract_java_annotation_primary_arg('@GetMapping("/api")') == "/api"

    def test_named_string_value(self) -> None:
        assert extract_java_annotation_primary_arg('@RequestMapping(value="/v1")') == "/v1"


class TestJavaExtendsCompanyKafkaListener:
    def test_immomo_fqn_with_generics(self) -> None:
        bases = [
            "com.immomo.kafka.spring.autoconfigure.core.KafkaListener<OrderEvent>",
        ]
        assert _java_extends_company_kafka_listener(bases) is True

    def test_simple_kafka_listener_extends(self) -> None:
        assert _java_extends_company_kafka_listener(["KafkaListener<Foo>"]) is True

    def test_unrelated_base(self) -> None:
        assert _java_extends_company_kafka_listener(["java.lang.Object"]) is False


class TestExtractKafkaListenerTopicsFromJavaText:
    def test_topics_in_embedded_annotation(self) -> None:
        src = """
        public class X extends KafkaListener {
            @KafkaListener(topics = "orders-in")
            public void on() {}
        }
        """
        assert _extract_kafka_listener_topics_from_java_text(src) == ["orders-in"]

    def test_fqn_kafka_listener(self) -> None:
        src = '@org.springframework.kafka.annotation.KafkaListener("ev") void m();'
        assert _extract_kafka_listener_topics_from_java_text(src) == ["ev"]
