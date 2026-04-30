"""Tests for AdaptiveBatchSizer."""


def test_initial_size():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=80)
    assert sizer.next_size() == 80


def test_shrink_on_timeout():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=80, min_size=20)
    sizer.record(batch_size=80, elapsed_s=100, success=True)
    assert sizer.next_size() == 40


def test_shrink_on_failure():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=80, min_size=20)
    sizer.record(batch_size=80, elapsed_s=50, success=False)
    assert sizer.next_size() == 40


def test_grow_on_fast_success():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=80, max_size=150)
    sizer.record(batch_size=80, elapsed_s=20, success=True)
    assert sizer.next_size() == 104


def test_no_grow_if_batch_size_differs():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=80, max_size=150)
    sizer.record(batch_size=40, elapsed_s=20, success=True)
    assert sizer.next_size() == 80


def test_respects_min_size():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=30, min_size=20)
    sizer.record(batch_size=30, elapsed_s=100, success=True)
    assert sizer.next_size() >= 20


def test_respects_max_size():
    from wiki.adaptive_batch import AdaptiveBatchSizer
    sizer = AdaptiveBatchSizer(initial_size=140, max_size=150)
    sizer.record(batch_size=140, elapsed_s=20, success=True)
    assert sizer.next_size() <= 150
