import unittest

from worldcup_predictor.localization import (
    is_first_division_league,
    to_api_name,
    to_beijing_time,
    translate_league_display,
    translate_league_name,
    translate_name,
    translate_team_display,
)


class LocalizationTest(unittest.TestCase):
    def test_translates_team_and_league_names(self):
        self.assertEqual(translate_name("team", "Mexico"), "墨西哥")
        self.assertEqual(translate_name("team", "Napoli"), "那不勒斯")
        self.assertEqual(translate_name("team", "Udinese"), "乌迪内斯")
        self.assertEqual(translate_name("team", "USA"), "美国")
        self.assertEqual(translate_name("team", "Osipovichy"), "奥西波维奇")
        self.assertEqual(translate_name("team", "Minsk II"), "明斯克二队")
        self.assertEqual(translate_name("league", "World Cup"), "国际足联世界杯")
        self.assertEqual(translate_league_name("1. Division", "Belarus"), "白俄罗斯足球甲级联赛")
        self.assertEqual(translate_league_name("1. Division", "Kazakhstan"), "哈萨克斯坦足球甲级联赛")
        self.assertEqual(translate_name("team", "Astana II"), "阿斯塔纳二队")
        self.assertEqual(translate_name("team", "Mangasport"), "曼加斯波特")
        self.assertEqual(translate_team_display("Omarska", "主队"), "奥马尔斯卡")
        self.assertEqual(translate_team_display("FK Vlasenica", "客队"), "弗拉塞尼察")
        self.assertEqual(translate_league_display("1st League - RS", "Bosnia"), "波黑塞族共和国足球甲级联赛")

    def test_unmapped_public_names_preserve_api_identity(self):
        self.assertEqual(translate_team_display("Unmapped Club", "主队"), "Unmapped Club")
        self.assertEqual(translate_league_display("Unknown Competition", "Exampleland"), "Unknown Competition")

    def test_identifies_first_division_without_confusing_lower_leagues(self):
        self.assertTrue(is_first_division_league("1. Division", "Kazakhstan"))
        self.assertTrue(is_first_division_league("Serie A", "Italy"))
        self.assertFalse(is_first_division_league("League Two", "China"))

    def test_can_use_chinese_team_name_for_api_lookup(self):
        self.assertEqual(to_api_name("team", "墨西哥"), "Mexico")
        self.assertEqual(to_api_name("team", "美国"), "USA")

    def test_formats_beijing_time(self):
        self.assertEqual(to_beijing_time("2026-06-12T00:00:00+00:00"), "2026-06-12 08:00 北京时间")


if __name__ == "__main__":
    unittest.main()
