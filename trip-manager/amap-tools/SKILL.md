---
name: amap-tools
description: >
  高德地图 API 集成。提供地理编码、POI 搜索、路径规划、天气查询能力。
  用于行程规划：查景点、算距离、查天气。
---

# 高德地图 amap-tools

## 配置

```bash
# Master 申请: https://lbs.amap.com/dev/key/app
# 写入 ~/.hermes/trip-env.sh
export AMAP_API_KEY="你的_Web服务_API_Key"
```

需要勾选权限：Web 服务 API（地理编码、路径规划、POI 搜索、天气查询）。

## 用法

### POI 搜索：景点/酒店/餐厅

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/amap.py poi \
    --keyword "四姑娘山" \
    --city "成都"
```

### 路径规划：A→B 距离/时间

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/amap.py route \
    --origin "上海" \
    --destination "北京" \
    --mode driving  # driving/walking/transit/riding
```

### 天气查询

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/amap.py weather \
    --city "四姑娘山" \
    --extensions all  # forecast(未来)/current(实时)
```

### 地理编码：地名 → 坐标

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/amap.py geocode \
    --address "四姑娘山"
```

### 完整行程规划（整合）

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/amap.py plan-trip \
    --destination "四姑娘山" \
    --days 3 \
    --origin "成都"
```

输出每日建议路线 + 景点 + 天气。