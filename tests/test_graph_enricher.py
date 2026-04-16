"""Tests for post-indexing graph enrichment (API endpoints + architecture layers)."""

import pytest

from indexer.graph_enricher import (
    _annotation_simple_name,
    _classify_architecture_layer,
    _join_api_paths,
    _kafka_topic_from_listener,
    _parse_annotation_arg,
    _pick_http_annotation,
    _class_request_mapping_base,
    _topics_from_kafka_producer_snippet,
)


class TestParseAnnotationArg:
    def test_simple_string_arg(self):
        assert _parse_annotation_arg('@GetMapping("/api/users")') == "/api/users"

    def test_single_quote(self):
        assert _parse_annotation_arg("@app.get('/items')") == "/items"

    def test_no_parens(self):
        assert _parse_annotation_arg("@Service") == ""

    def test_empty_parens(self):
        assert _parse_annotation_arg("@Service()") == ""

    def test_named_value_arg(self):
        assert _parse_annotation_arg('@RequestMapping(value="/api")') == "/api"

    def test_nested_parens(self):
        assert _parse_annotation_arg('@GetMapping(path="/a(b)")') == "/a(b)"


class TestAnnotationSimpleName:
    def test_simple(self):
        assert _annotation_simple_name("@Service") == "Service"

    def test_with_args(self):
        assert _annotation_simple_name('@GetMapping("/api")') == "GetMapping"

    def test_fqn(self):
        assert _annotation_simple_name("@org.springframework.stereotype.Service") == "Service"

    def test_at_sign_stripped(self):
        assert _annotation_simple_name("@Component") == "Component"

    def test_no_at_sign(self):
        assert _annotation_simple_name("Service") == "Service"


class TestJoinApiPaths:
    def test_both_present(self):
        assert _join_api_paths("/api", "/users") == "/api/users"

    def test_base_only(self):
        assert _join_api_paths("/api", "") == "/api"

    def test_rel_only(self):
        assert _join_api_paths("", "/users") == "/users"

    def test_both_empty(self):
        assert _join_api_paths("", "") == ""

    def test_trailing_slash_base(self):
        assert _join_api_paths("/api/", "/users") == "/api/users"

    def test_no_leading_slash_rel(self):
        assert _join_api_paths("/api", "users") == "/api/users"

    def test_root_base(self):
        assert _join_api_paths("/", "items") == "/items"


class TestPickHttpAnnotation:
    def test_get_mapping(self):
        ann = ['@GetMapping("/users")']
        raw, method, path = _pick_http_annotation(ann)
        assert method == "GET"
        assert path == "/users"

    def test_post_mapping(self):
        ann = ['@PostMapping("/create")']
        raw, method, path = _pick_http_annotation(ann)
        assert method == "POST"
        assert path == "/create"

    def test_request_mapping_fallback(self):
        ann = ['@RequestMapping("/base")']
        raw, method, path = _pick_http_annotation(ann)
        assert method == "*ALL*"
        assert path == "/base"

    def test_flask_get(self):
        ann = ['@app.get("/items")']
        raw, method, path = _pick_http_annotation(ann)
        assert method == "GET"
        assert path == "/items"

    def test_no_http_annotation(self):
        ann = ["@Service", "@Autowired"]
        raw, method, path = _pick_http_annotation(ann)
        assert method is None
        assert raw is None

    def test_empty_list(self):
        raw, method, path = _pick_http_annotation([])
        assert method is None

    def test_none_input(self):
        raw, method, path = _pick_http_annotation(None)
        assert method is None

    def test_specific_beats_request_mapping(self):
        ann = ['@RequestMapping("/api")', '@GetMapping("/users")']
        raw, method, path = _pick_http_annotation(ann)
        assert method == "GET"
        assert path == "/users"


class TestClassRequestMappingBase:
    def test_extracts_base_path(self):
        ann = ['@RestController', '@RequestMapping("/api/v1")']
        assert _class_request_mapping_base(ann) == "/api/v1"

    def test_no_request_mapping(self):
        ann = ["@Service"]
        assert _class_request_mapping_base(ann) == ""

    def test_empty(self):
        assert _class_request_mapping_base(None) == ""
        assert _class_request_mapping_base([]) == ""


class TestKafkaTopicFromListener:
    def test_simple_topic(self):
        ann = '@KafkaListener(topics = "user-events")'
        assert _kafka_topic_from_listener(ann) == "user-events"

    def test_topics_brace(self):
        ann = '@KafkaListener(topics = {"order-topic"})'
        assert _kafka_topic_from_listener(ann) == "order-topic"

    def test_no_topics_arg_falls_back(self):
        ann = '@KafkaListener("fallback-topic")'
        assert _kafka_topic_from_listener(ann) == "fallback-topic"

    def test_no_parens(self):
        assert _kafka_topic_from_listener("@KafkaListener") == ""


class TestTopicsFromKafkaProducerSnippet:
    def test_send_sync_topic(self):
        snippet = 'producer.sendSync("orders-outbound", payload)'
        assert _topics_from_kafka_producer_snippet(snippet) == ["orders-outbound"]

    def test_send_async_topic(self):
        snippet = "kafkaProducer.sendAsync('events', msg, callback)"
        assert _topics_from_kafka_producer_snippet(snippet) == ["events"]

    def test_legacy_send_still_extracts(self):
        snippet = '.send("legacy-topic", v)'
        assert _topics_from_kafka_producer_snippet(snippet) == ["legacy-topic"]

    def test_empty_or_none(self):
        assert _topics_from_kafka_producer_snippet(None) == []
        assert _topics_from_kafka_producer_snippet("") == []


class TestClassifyArchitectureLayer:
    def test_http_controller(self):
        assert _classify_architecture_layer(["http_controller"], None) == "presentation"

    def test_rpc_provider(self):
        assert _classify_architecture_layer(["rpc_provider"], None) == "rpc"

    def test_service(self):
        assert _classify_architecture_layer(["service"], None) == "business"

    def test_repository(self):
        assert _classify_architecture_layer(["repository"], None) == "data_access"

    def test_message_listener(self):
        assert _classify_architecture_layer(["message_listener"], None) == "messaging"

    def test_component(self):
        assert _classify_architecture_layer(["component"], None) == "infrastructure"

    def test_fqn_controller_fallback(self):
        assert _classify_architecture_layer(None, "com.app.controller.UserController") == "presentation"

    def test_fqn_service_fallback(self):
        assert _classify_architecture_layer(None, "com.app.service.UserService") == "business"

    def test_fqn_dao_fallback(self):
        assert _classify_architecture_layer(None, "com.app.dao.UserDao") == "data_access"

    def test_fqn_model_fallback(self):
        assert _classify_architecture_layer(None, "com.app.model.User") == "model"

    def test_fqn_config_fallback(self):
        assert _classify_architecture_layer(None, "com.app.config.AppConfig") == "infrastructure"

    def test_unknown(self):
        assert _classify_architecture_layer(None, None) == "unknown"

    def test_empty_roles(self):
        assert _classify_architecture_layer([], None) == "unknown"

    def test_priority_http_controller_over_service(self):
        assert _classify_architecture_layer(["http_controller", "service"], None) == "presentation"

    def test_fqn_extended_messaging_listener(self):
        assert _classify_architecture_layer(None, "com.app.listener.OrderListener") == "messaging"

    def test_fqn_extended_messaging_kafka_event(self):
        assert _classify_architecture_layer(None, "com.app.kafka.event.OrderEvent") == "messaging"

    def test_fqn_domain_event_goes_to_model(self):
        assert _classify_architecture_layer(None, "com.app.domain.event.OrderCreated") == "model"

    def test_fqn_plain_events_goes_to_model(self):
        assert _classify_architecture_layer(None, "com.app.events.OrderCreated") == "model"

    def test_fqn_extended_rpc_moa(self):
        assert _classify_architecture_layer(None, "com.app.moa.UserMoaClient") == "rpc"

    def test_fqn_extended_rpc_external(self):
        assert _classify_architecture_layer(None, "com.app.external.PaymentGateway") == "rpc"

    def test_fqn_extended_model_bean(self):
        assert _classify_architecture_layer(None, "com.app.bean.UserBean") == "model"

    def test_fqn_extended_model_domain(self):
        assert _classify_architecture_layer(None, "com.app.domain.User") == "model"

    def test_fqn_extended_data_access_repo(self):
        assert _classify_architecture_layer(None, "com.app.repo.UserRepo") == "data_access"

    def test_fqn_extended_business_handler(self):
        assert _classify_architecture_layer(None, "com.app.handler.OrderHandler") == "business"

    def test_fqn_extended_infrastructure_util(self):
        assert _classify_architecture_layer(None, "com.app.util.StringHelper") == "infrastructure"

    def test_fqn_extended_infrastructure_adapter(self):
        assert _classify_architecture_layer(None, "com.app.adapter.RedisAdapter") == "infrastructure"
