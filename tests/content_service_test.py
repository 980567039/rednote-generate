from backend.services.content import ContentService


def test_parse_json_response_accepts_literal_newlines_in_string_values():
    service = ContentService.__new__(ContentService)
    payload = service._parse_json_response('''{
      "titles": ["像素角色图"],
      "copywriting": "第一段
第二段",
      "tags": ["像素画"]
    }''')

    assert payload["copywriting"] == "第一段\n第二段"
