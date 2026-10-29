from htmlscraper.my_provider import HealthProxyProvider

URLS = ["http://u1:p1@127.0.0.1:8001",
        "http://u2:p2@127.0.0.1:8002",
        "http://u3:p3@127.0.0.1:8003"]


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(clock=None):
    return HealthProxyProvider(URLS, cooldown=300.0, clock=clock or FakeClock())


def test_current_is_valid_url():
    assert make().current() in URLS


def test_rotate_changes_route():
    p = make()
    first = p.current()
    p.report_blocked(first, 403)
    assert p.rotate("ForbiddenError") is True
    assert p.current() != first


def test_rotate_false_when_all_blocked():
    p = make()
    for _ in range(len(URLS)):
        p.report_blocked(p.current(), 403)
        if not p.rotate("x"):
            break
    assert p.rotate("x") is False


def test_cooldown_expires():
    clock = FakeClock()
    p = make(clock)
    for _ in range(len(URLS)):
        p.report_blocked(p.current(), 429)
        p.rotate("x")
    assert p.rotate("x") is False
    clock.t += 301
    assert p.rotate("x") is True


def test_report_methods_never_raise():
    p = make()
    p.report_success(None)
    p.report_success("http://unknown:1")
    p.report_blocked(None, 403)
    p.report_blocked("http://unknown:1", None)


def test_success_clears_rest():
    p = make()
    cur = p.current()
    p.report_blocked(cur, 429)
    p.report_success(cur)
    assert cur not in p._rest_until


def test_describe_hides_credentials():
    d = make().describe()
    for secret in ("u1", "p1", "u2", "p2", "u3", "p3"):
        assert secret not in d
