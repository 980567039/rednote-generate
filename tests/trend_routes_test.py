def test_trends_returns_local_demo_items(client):
    response = client.get("/api/trends")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["source"] == "local_demo"
    assert len(payload["trends"]) >= 3
    assert all(item["title"] and item["topic"] for item in payload["trends"])
