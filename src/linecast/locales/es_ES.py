"""European Spanish: only the words that differ from es.py.

A key left out here reads as in Spanish, then English.
"""


SETTINGS = {
    # Latin American Spanish keeps the point, as Mexico and most of the
    # region do; Spain takes the comma.
    "decimal": ",",
}


HELP = {
            "key_enter": "intro",
            "forecast": "recorrer la previsión",
            "refresh": "actualizar la previsión",
}


WEATHER = {
               "forecast_stale": "Esta previsión es del {day}; no se pudo obtener una más reciente.",
               "forecast_stale_at": "Esta previsión es del {day}; no se pudo obtener una más reciente a las {time}.",
               "forecast_fetching": "Obteniendo una previsión más reciente…",
               "retry_key": "Pulse r para reintentar.",
               "hist_near_avg": "cerca de la media",
               "hist_above_avg": "{diff} por encima de la media",
               "hist_below_avg": "{diff} por debajo de la media",
}


CONDITIONS = {
                  2: "Intervalos nubosos",
                  1: "Poco nuboso",
                  3: "Cubierto",
                  "mostly_cloudy": "Nuboso",
}


PRECIP = {  # European Spanish: AEMET's "débil" where Latin America says "ligera"
              51: "llovizna débil", 61: "lluvia débil", 71: "nieve débil",
              80: "chubascos débiles",
}


LOCATIONS = {
    "add": "Añadir ubicación",
}


RADAR = {
             "forecast": "previsión",
}


MAPS = {
            "search_hint": "↑↓ elegir · intro ir · esc cerrar",
            "mode_street": "callejero",
            "help_view": "callejero · relieve",
            "profile_car": "en coche",
            "hov_trunk": "autovía",
}


SKY = {
           "search_jump": "intro de nuevo para ir a ese momento",
}
