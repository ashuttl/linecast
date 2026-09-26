"""Hong Kong Chinese: only the words that differ from zh_Hant.py.

A key left out here reads as in Traditional Chinese, then English.
"""


HELP = {
            "key_space": "空格鍵",
            "alert": "閱讀警告",
            "alerts": "警告圖層",
            "browser": "在瀏覽器中開啟警告",
}


WEATHER = {
               "alerts_unavailable": "未能取得警告資訊。",
               "alerts_stale": "警告資訊截至{when}，未能取得更新的資訊。",
               "on_two_days": "{first}及{second}",
               "from_day_to_day": "{first}至{last}",
               "tomorrow_and_day": "明日及{second}",
               "from_tomorrow_to_day": "明日至{last}",
               "on_tomorrow": "明日",
               "credit_alerts": "警告來源：{source}",
               "credit_current": "現時天氣來源：{source}",
               "chance": "降水概率 {p}",
               "chance_of": "降水概率 {p}",
               "space_to_now": "按空格鍵回到現在",
               "will_be_then": "最高氣溫{comparison}",
               "today_ref": "今日",
               "yesterday": "昨日",
               "tomorrow_subj": "明日最高氣溫",
               "today_subj": "今日最高氣溫",
               "early_tomorrow_morning": "明日清晨",
               "tomorrow_morning": "明早",
               "tomorrow_afternoon": "明日下午",
               "tomorrow_evening": "明日傍晚",
               "this_morning": "今早",
               "this_afternoon": "今日下午",
               "this_evening": "今日傍晚",
}


CONDITIONS = {
                  0: "天晴",
                  1: "大致天晴",
                  2: "天晴間中多雲",
                  "mostly_cloudy": "大致多雲",
                  3: "密雲",
                  61: "微雨",
                  80: "幾陣驟雨",
                  81: "驟雨",
                  82: "大驟雨",
                  95: "雷暴",
                  96: "雷暴",
                  99: "雷暴",
}


PRECIP = {
              61: "微雨",
              # Not the header's 幾陣驟雨: a few showers do not stop or turn
              80: "零散驟雨",
              81: "驟雨",
              82: "大驟雨",
              95: "雷暴",
              96: "雷暴",
              99: "雷暴",
}


RADAR = {
             "hint": "空格鍵 播放/暫停 · 捲動/←→ 逐格 · +/- 縮放 · 拖曳平移 / wasd · c 氣溫 · W 風 · t 主題 · S 衛星 · q 離開",
             "no_frames": "無雷達圖像",
}


MAPS = {
            "hov_transit": "公共交通路線",
            "hov_ramp": "支路",
            "hov_trunk": "主幹道",
            "profile_car": "駕車",
            "profile_bike": "單車",
            "poi_ferry": "渡輪 · 碼頭",
            "streets_unavailable": "地圖圖塊不可用 ({err})",
            "offline": "無地圖圖塊",
}


TIDES = {
             "space_to_now": "按空格鍵回到現在",
             "swell": "湧浪",
}


SUNSHINE = {
                "solar_noon": "日中天",
}


SKY_CULTURES = {
    "tongan": "湯加",
}
