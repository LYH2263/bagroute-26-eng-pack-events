# BagRoute

投递装袋：按路线订户顺序装袋，重量与体积双约束，超限拒收。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4300 |
| API | http://localhost:9300 |
| API 文档 | http://localhost:9300/docs |
| Postgres | localhost:5444 |

健康检查：`GET http://localhost:9300/api/health`

## 页面

- `/routes` — 路线
- `/stops` — 订户点
- `/pack` — 装袋
- `/bags` — 袋明细
- `/rejects` — 拒收
- `/weights` — 袋重

## 接口

- `POST /api/pack` — 执行装袋，每次在 `pack_events` 旁路追加一条运行事件
- `GET /api/events?route_id=…` — 只读查询运行事件，按路线倒序（route_id 大的在前，同路线新事件在前），`route_id` 可选

### 运行事件字段（pack_events）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | int | 事件主键，每次执行递增，用于区分同一路线的连续装袋 |
| route_id | int | 所属路线 |
| bag_count | int | 本次装出的袋数 |
| reject_count | int | 本次拒收的订户点数 |
| outcome | str | 结果：`packed`（装袋成功）/ `rejected`（有业务拒收） |
| created_at | datetime | 执行时间（UTC） |

事件表只追加：重复装袋会重建袋明细与拒收表，但历史事件不覆盖、不删除；事件表不替代袋明细（`pack_bags` / `bag_items`）或拒收表（`reject_records`）。

## 使用说明

1. 查看路线与订户点顺序。
2. 在装袋页选择路线执行双约束装袋。
3. 袋明细与袋重查看结果，拒收页查看超限订户。

## 开发与测试

```bash
docker compose exec api pytest -q
```
