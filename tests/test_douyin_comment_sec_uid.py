import unittest

from app.platforms.douyin.extract import parse_comment, parse_creator_comment


class DouyinCommentSecUidTests(unittest.TestCase):
    def test_public_comment_extracts_sec_uid(self):
        parsed = parse_comment({
            "cid": "comment-1",
            "text": "hello",
            "user": {"nickname": "visitor", "sec_uid": "MS4wLj-public"},
        })

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["user_sec_uid"], "MS4wLj-public")

    def test_public_comment_extracts_ip_label(self):
        parsed = parse_comment({
            "cid": "comment-region-public",
            "ip_label": "北京",
            "user": {"nickname": "visitor"},
        })

        self.assertEqual(parsed["ip_label"], "北京")

    def test_browser_comment_accepts_nested_ip_location_alias(self):
        parsed = parse_comment({
            "cid": "comment-region-browser",
            "extra": {"ip_location": "上海"},
            "user": {"nickname": "visitor"},
        })

        self.assertEqual(parsed["ip_label"], "上海")

    def test_creator_comment_accepts_sec_uid_alias(self):
        parsed = parse_creator_comment({
            "comment_id": "comment-2",
            "content": "hello",
            "region": {"label": "广东"},
            "user_info": {"name": "visitor", "secUserId": "MS4wLj-creator"},
        })

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["user_sec_uid"], "MS4wLj-creator")
        self.assertEqual(parsed["ip_label"], "广东")


if __name__ == "__main__":
    unittest.main()
