from wiki.domain_merger import merge_small_domains


class FakeDomain:
    def __init__(self, name, modules):
        self.name = name
        self.modules = list(modules)
        self.children = []
        self.description = ""


def test_merge_single_module_domain():
    domains = [
        FakeDomain("Big", ["A", "B", "C", "D"]),
        FakeDomain("Small", ["E"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 1
    assert "E" in result[0].modules


def test_no_merge_if_all_large():
    domains = [
        FakeDomain("A", ["m1", "m2", "m3"]),
        FakeDomain("B", ["m4", "m5", "m6"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 2


def test_merge_preserves_large_domains():
    domains = [
        FakeDomain("Big", ["A", "B", "C"]),
        FakeDomain("Tiny1", ["D"]),
        FakeDomain("Tiny2", ["E"]),
    ]
    result = merge_small_domains(domains, min_size=3)
    assert len(result) == 1
    assert len(result[0].modules) == 5
