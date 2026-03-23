---
name: weather
description: Get current weather and forecast info. Invoke when user asks about weather, temperature, rain, or forecast.
triggers: weather, forecast, temperature, rain, wind, humidity, 天气, 温度, 降雨
always: false
metadata: {"nanobot":{"requires":{"bins":["curl"],"env":[]}}}
---
Use wttr.in first.
If city is missing, ask for city.
Prefer concise output: condition, temperature, humidity, wind.
