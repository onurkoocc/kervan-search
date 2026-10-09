import pytest

from conftest import ids


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("How do I reschedule my delivery to another day?", "reschedule-delivery"),
        ("my parcel arrived broken", "damaged-parcel"),
        ("my package never arrived, I think it is lost", "lost-parcel"),
        ("what is the verification code, last four digits of the phone", "verification-code"),
        ("where is my parcel, tracking number KRV00012345", "track-shipment"),
        ("customs duty and taxes for an international shipment", "customs"),
        ("I want to send a parcel back to the sender", "returns"),
        ("how do I open a support ticket", "open-ticket"),
        ("what time does the courier come, morning or evening window", "delivery-windows"),
        ("nobody was home, failed delivery attempt", "missed-delivery"),
        ("my delivery is late and delayed", "late-delivery"),
        ("what does OUT_FOR_DELIVERY status mean", "shipment-statuses"),
        ("branch opening hours on saturday", "branches-and-hours"),
    ],
)
def test_best_match(client, query, expected):
    response = client.get("/search", params={"q": query})
    assert response.status_code == 200
    assert ids(response)[0] == expected


def test_result_shape(client):
    body = client.get("/search", params={"q": "reschedule delivery"}).json()
    assert set(body) == {"results"}
    for result in body["results"]:
        assert set(result) == {"id", "title", "snippet", "score"}
        assert isinstance(result["score"], float) and 0 < result["score"] <= 1
        assert result["snippet"] and len(result["snippet"]) <= 200


def test_results_are_sorted_best_first(client):
    scores = [r["score"] for r in client.get("/search", params={"q": "parcel delivery", "k": 10}).json()["results"]]
    assert scores == sorted(scores, reverse=True)


def test_snippet_is_the_matching_paragraph(client):
    first = client.get("/search", params={"q": "last four digits of the phone", "k": 1}).json()["results"][0]
    assert "last four digits" in first["snippet"]


def test_reschedule_article_states_the_core_rules(client):
    first = client.get("/search", params={"q": "how far ahead can I reschedule", "k": 1}).json()["results"][0]
    assert first["id"] == "reschedule-delivery"
    text = client.get("/search", params={"q": "tomorrow 14 days ahead", "k": 1}).json()["results"][0]["snippet"]
    assert "tomorrow" in text and "14 days" in text


def test_no_match_gives_no_results(client):
    response = client.get("/search", params={"q": "zzzz qqqq"})
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_whitespace_query_gives_no_results(client):
    assert client.get("/search", params={"q": "   "}).json() == {"results": []}


@pytest.mark.parametrize(("k", "count"), [(None, 3), ("1", 1), ("3", 3), ("10", 10)])
def test_k_within_bounds(client, k, count):
    params = {"q": "parcel delivery"} | ({"k": k} if k else {})
    response = client.get("/search", params=params)
    assert response.status_code == 200
    assert len(response.json()["results"]) == count


@pytest.mark.parametrize("k", ["0", "11", "-1", "abc", "2.5", ""])
def test_k_out_of_bounds_is_refused(client, k):
    response = client.get("/search", params={"q": "parcel", "k": k})
    assert response.status_code == 422


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x" * 501}])
def test_bad_query_is_refused(client, params):
    assert client.get("/search", params=params).status_code == 422


def test_query_of_max_length_is_accepted(client):
    assert client.get("/search", params={"q": "parcel " * 71 + "abc"}).status_code == 200


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
